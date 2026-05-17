"""
Automated RINEX Downloader
===========================
B — Rolling cache: rinex_cache/YYYY/DOY/ keeps today + yesterday for all corridor stations.
C — Station aliases: CDDIS directory listing + rinex_station_aliases.json resolve 4-char codes.

Event flow: refresh cache -> copy cache -> download any missing -> rinex_live/<event_id>/
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
    from requests.auth import HTTPBasicAuth
except ImportError:
    print("pip install requests")
    raise

EVENT_QUEUE_FILE = "event_queue.json"
RINEX_BASE_DIR = "rinex_live"
RINEX_CACHE_DIR = "rinex_cache"
ALIASES_FILE = "rinex_station_aliases.json"
CATALOG_FILE = "igs_station_catalog.json"
LOG_FILE = "downloader.log"
CDDIS_BASE = "https://cddis.nasa.gov/archive/gnss/data/daily"
CDDIS_SUFFIXES = (".gz", ".Z")
CACHE_DAYS = 3  # rolling UTC days kept on disk
EVENT_DOY_OFFSETS = (-1, 0, 1)  # quake day ±1 for propagation window
DISCOVERY_RADIUS_KM = 3200  # auto-add catalog sites within this range of epicenter

CORRIDOR_STATIONS = {
    "guam": [
        "mizu", "usud", "aira", "tskb", "yssz", "khaj",
        "pimo", "cnmr", "pohn",
        "guam", "kwj1", "noum",
        "mkea", "kokb", "hnlc", "holb",
    ],
    "chat": ["chat", "auck", "mkea", "kokb", "hnlc", "sant", "iqqe"],
    "thti": ["thti", "thtg", "auck", "noum", "mkea", "kokb", "savo", "faf2"],
    None: ["mkea", "kokb", "hnlc", "guam", "mizu", "usud"],
}

RINEX_HREF_RE = re.compile(
    r'href="([a-z0-9]{4})(\d{3})0\.(\d{2})([on])\.(?:gz|Z)\s*"',
    re.IGNORECASE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

_listing_cache: dict[tuple, set[str]] = {}


def all_corridor_station_ids() -> list[str]:
    seen: set[str] = set()
    for stations in CORRIDOR_STATIONS.values():
        for s in stations:
            seen.add(s.lower())
    for s in load_station_catalog():
        seen.add(s.lower())
    return sorted(seen)


def haversine_km(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2

    r = 6371.0
    p1, p2 = radians(lat1), radians(lat2)
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(p1) * cos(p2) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def load_station_catalog() -> dict[str, dict]:
    p = Path(CATALOG_FILE)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k.lower(): v for k, v in data.items() if not k.startswith("_")}


def discover_stations_near_epicenter(
    epi_lat: float,
    epi_lon: float,
    year: int,
    doy: int,
    yr2: str,
    sess: requests.Session,
    aliases: dict[str, list[str]],
    max_km: float = DISCOVERY_RADIUS_KM,
) -> list[str]:
    """Pick catalog stations on CDDIS for this DOY within max_km of epicenter."""
    catalog = load_station_catalog()
    if not catalog:
        return []
    sites_o = fetch_cddis_listing(year, doy, yr2, "o", sess)
    sites_n = fetch_cddis_listing(year, doy, yr2, "n", sess)
    found: list[tuple[float, str]] = []
    for logical, meta in catalog.items():
        code = resolve_station_code(logical, sites_o, sites_n, aliases)
        if not code:
            continue
        dist = haversine_km(epi_lat, epi_lon, meta["lat"], meta["lon"])
        if dist <= max_km:
            found.append((dist, logical))
    found.sort(key=lambda x: x[0])
    picked = [s for _, s in found]
    if picked:
        log.info(f"  CDDIS discovery ({year}/{doy:03d}): {picked} within {max_km:.0f} km")
    return picked


def stations_for_event(event: dict) -> list[str]:
    """Corridor list + epicenter discovery (unique, corridor order first)."""
    anchor = event.get("primary_anchor")
    base = list(CORRIDOR_STATIONS.get(anchor, CORRIDOR_STATIONS[None]))
    lat, lon = event.get("lat"), event.get("lon")
    if lat is None or lon is None:
        return base
    year, doy, yr2, _ = quake_to_doy(event["quake_utc"])
    user, pwd = get_credentials()
    if not user:
        return base
    sess = earthdata_session(HTTPBasicAuth(user, pwd))
    aliases = load_aliases()
    discovered = discover_stations_near_epicenter(
        lat, lon, year, doy, yr2, sess, aliases
    )
    merged: list[str] = []
    seen: set[str] = set()
    for s in base + discovered:
        k = s.lower()
        if k not in seen:
            seen.add(k)
            merged.append(k)
    return merged


def load_aliases() -> dict[str, list[str]]:
    p = Path(ALIASES_FILE)
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: [x.lower() for x in v] for k, v in data.items() if not k.startswith("_")}


def save_aliases(aliases: dict[str, list[str]]) -> None:
    out = {"_note": "Logical pipeline IDs -> CDDIS 4-char codes (auto-updated)."}
    for k in sorted(aliases):
        out[k] = sorted(set(aliases[k]))
    Path(ALIASES_FILE).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")


def load_queue():
    if not Path(EVENT_QUEUE_FILE).exists():
        log.error(f"{EVENT_QUEUE_FILE} not found — run usgs_listener.py first")
        return None
    return json.loads(Path(EVENT_QUEUE_FILE).read_text(encoding="utf-8"))


def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2), encoding="utf-8")


def get_credentials():
    user = os.environ.get("EARTHDATA_USER")
    pwd = os.environ.get("EARTHDATA_PASS")
    if not user or not pwd:
        script_dir = Path(__file__).parent
        for env_file in [Path(".env"), script_dir / ".env"]:
            if env_file.exists():
                log.info(f"Loading credentials from {env_file.resolve()}")
                for line in env_file.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if line.startswith("EARTHDATA_USER="):
                        user = line.split("=", 1)[1].strip()
                    if line.startswith("EARTHDATA_PASS="):
                        pwd = line.split("=", 1)[1].strip()
                if user and pwd:
                    break
    if not user or not pwd:
        log.error("No Earthdata credentials found.")
        return None, None
    return user, pwd


def earthdata_session(auth: HTTPBasicAuth) -> requests.Session:
    class _S(requests.Session):
        def rebuild_auth(self, pr, r):
            if self.auth:
                pr.prepare_auth(self.auth, r.url)

    s = _S()
    s.auth = auth
    return s


def quake_to_doy(quake_utc_str):
    dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))
    doy = dt.timetuple().tm_yday
    yr2 = str(dt.year)[-2:]
    return dt.year, doy, yr2, dt


def cache_dir(year: int, doy: int) -> Path:
    return Path(RINEX_CACHE_DIR) / str(year) / f"{doy:03d}"


def build_cddis_candidates(year, doy, yr2, station_code: str, ftype: str = "o"):
    base = f"{station_code}{doy:03d}0.{yr2}{ftype}"
    return [
        (f"{CDDIS_BASE}/{year}/{doy:03d}/{yr2}{ftype}/{base}{suf}", base + suf)
        for suf in CDDIS_SUFFIXES
    ]


def fetch_cddis_listing(year: int, doy: int, yr2: str, ftype: str, sess: requests.Session) -> set[str]:
    key = (year, doy, ftype)
    if key in _listing_cache:
        return _listing_cache[key]
    url = f"{CDDIS_BASE}/{year}/{doy:03d}/{yr2}{ftype}/"
    sites: set[str] = set()
    try:
        r = sess.get(url, timeout=90)
        if r.status_code == 200:
            for m in RINEX_HREF_RE.finditer(r.text):
                sites.add(m.group(1).lower())
    except Exception as e:
        log.warning(f"CDDIS listing failed {url}: {e}")
    _listing_cache[key] = sites
    log.info(f"CDDIS listing {year}/{doy:03d}/{yr2}{ftype}: {len(sites)} sites")
    return sites


def resolve_station_code(
    logical: str,
    sites_o: set[str],
    sites_n: set[str],
    aliases: dict[str, list[str]],
) -> str | None:
    """Map pipeline station id -> 4-char code present on CDDIS (C)."""
    logical = logical.lower()
    candidates = [logical]
    candidates.extend(aliases.get(logical, []))
    seen: set[str] = set()
    for c in candidates:
        c = c.lower()
        if c in seen:
            continue
        seen.add(c)
        if c in sites_o or c in sites_n:
            aliases.setdefault(logical, [])
            if c not in aliases[logical]:
                aliases[logical].append(c)
            return c
    return None


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def download_file(url: str, dest_path: Path, sess: requests.Session) -> bool:
    if dest_path.exists() and dest_path.stat().st_size > 500:
        return True
    try:
        r = sess.get(url, timeout=120, stream=True)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        if dest_path.stat().st_size < 500:
            _safe_unlink(dest_path)
            return False
        if dest_path.read_bytes()[:1] == b"<":
            _safe_unlink(dest_path)
            return False
        return True
    except Exception as e:
        log.warning(f"  FAIL {dest_path.name}: {e}")
        _safe_unlink(dest_path)
        return False


def download_station_day_to_dir(
    year: int,
    doy: int,
    yr2: str,
    station_code: str,
    dest_dir: Path,
    sess: requests.Session,
    ftypes: tuple[str, ...] = ("o", "n"),
) -> int:
    n = 0
    for ftype in ftypes:
        for url, fname in build_cddis_candidates(year, doy, yr2, station_code, ftype):
            dest = dest_dir / fname
            if download_file(url, dest, sess):
                n += 1
                break
        time.sleep(0.35)
    return n


def refresh_rolling_cache(auth: HTTPBasicAuth, days: int = CACHE_DAYS) -> dict:
    """B — Keep last N UTC days of RINEX on disk for all corridor stations."""
    sess = earthdata_session(auth)
    aliases = load_aliases()
    now = datetime.now(timezone.utc)
    stats = {"days": [], "files": 0, "stations_hit": {}}

    log.info(f"Rolling RINEX cache ({days} UTC days) -> {RINEX_CACHE_DIR}/")
    for d_off in range(days):
        dt = now - timedelta(days=d_off)
        year, doy, yr2 = dt.year, dt.timetuple().tm_yday, str(dt.year)[-2:]
        dest = cache_dir(year, doy)
        dest.mkdir(parents=True, exist_ok=True)
        sites_o = fetch_cddis_listing(year, doy, yr2, "o", sess)
        sites_n = fetch_cddis_listing(year, doy, yr2, "n", sess)
        day_files = 0
        day_stations: list[str] = []

        for logical in all_corridor_station_ids():
            code = resolve_station_code(logical, sites_o, sites_n, aliases)
            if not code:
                continue
            n = download_station_day_to_dir(year, doy, yr2, code, dest, sess)
            if n > 0:
                day_files += n
                day_stations.append(logical)
            time.sleep(0.25)

        stats["days"].append(
            {"year": year, "doy": doy, "files": day_files, "stations": day_stations}
        )
        stats["files"] += day_files
        log.info(f"  cache {year}/{doy:03d}: {day_files} files, stations={day_stations}")

    save_aliases(aliases)
    meta = {
        "last_refresh_utc": now.isoformat(),
        "cache_days": days,
        "stats": stats,
    }
    Path(RINEX_CACHE_DIR, "cache_meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    return stats


def copy_from_cache(
    year: int,
    doy: int,
    yr2: str,
    station_codes: dict[str, str],
    event_dir: Path,
) -> int:
    """Copy cached files for resolved codes into event folder."""
    src_base = cache_dir(year, doy)
    if not src_base.exists():
        return 0
    copied = 0
    for _logical, code in station_codes.items():
        for ftype in ("o", "n"):
            for suf in CDDIS_SUFFIXES:
                fname = f"{code}{doy:03d}0.{yr2}{ftype}{suf}"
                src = src_base / fname
                if src.exists() and src.stat().st_size > 500:
                    dst = event_dir / fname
                    if not dst.exists():
                        shutil.copy2(src, dst)
                    copied += 1
                    break
    return copied


def resolve_corridor_stations(
    logical_stations: list[str],
    year: int,
    doy: int,
    yr2: str,
    sess: requests.Session,
    aliases: dict[str, list[str]],
) -> dict[str, str]:
    sites_o = fetch_cddis_listing(year, doy, yr2, "o", sess)
    sites_n = fetch_cddis_listing(year, doy, yr2, "n", sess)
    resolved: dict[str, str] = {}
    for logical in logical_stations:
        code = resolve_station_code(logical, sites_o, sites_n, aliases)
        if code:
            resolved[logical] = code
        else:
            log.warning(f"  No CDDIS code for station '{logical}' on {year}/{doy:03d}")
    return resolved


def _download_resolved_for_doy(
    year: int,
    doy: int,
    yr2: str,
    resolved: dict[str, str],
    event_dir: Path,
    sess: requests.Session,
) -> int:
    downloaded = copy_from_cache(year, doy, yr2, resolved, event_dir)
    for _logical, code in resolved.items():
        for ftype in ("o", "n"):
            for suf in CDDIS_SUFFIXES:
                fname = f"{code}{doy:03d}0.{yr2}{ftype}{suf}"
                if (event_dir / fname).exists():
                    break
            else:
                downloaded += download_station_day_to_dir(
                    year, doy, yr2, code, event_dir, sess, (ftype,)
                )
        time.sleep(0.35)
    return downloaded


def download_event(event, auth: HTTPBasicAuth):
    _, quake_doy, _, quake_dt = quake_to_doy(event["quake_utc"])
    logical_stations = stations_for_event(event)

    event_dir = Path(RINEX_BASE_DIR) / event["usgs_id"]
    event_dir.mkdir(parents=True, exist_ok=True)
    sess = earthdata_session(auth)
    aliases = load_aliases()

    log.info(f"\nRINEX for {event['usgs_id']} — {event.get('place', '')[:50]}")
    log.info(f"  Mw{event['magnitude']}  {event['quake_utc'][:16]}  DOY={quake_doy}")
    log.info(f"  Station list ({len(logical_stations)}): {logical_stations}")

    manifest: dict = {"usgs_id": event["usgs_id"], "days": [], "stations_requested": logical_stations}
    downloaded = 0
    epi_lat, epi_lon = event.get("lat"), event.get("lon")

    for day_off in EVENT_DOY_OFFSETS:
        dt = quake_dt + timedelta(days=day_off)
        year, doy, yr2 = dt.year, dt.timetuple().tm_yday, str(dt.year)[-2:]
        station_list = list(logical_stations)
        if epi_lat is not None and epi_lon is not None:
            extra = discover_stations_near_epicenter(
                epi_lat, epi_lon, year, doy, yr2, sess, aliases
            )
            for s in extra:
                if s not in station_list:
                    station_list.append(s)

        resolved = resolve_corridor_stations(station_list, year, doy, yr2, sess, aliases)
        if not resolved:
            log.warning(f"  No stations resolved for {year}/{doy:03d}")
            manifest["days"].append({"year": year, "doy": doy, "resolved": {}, "files": 0})
            continue

        n = _download_resolved_for_doy(year, doy, yr2, resolved, event_dir, sess)
        downloaded += n
        manifest["days"].append(
            {"year": year, "doy": doy, "resolved": resolved, "files": n}
        )
        log.info(f"  DOY {doy:03d}: {n} files, stations={list(resolved.keys())}")

    save_aliases(aliases)
    manifest["total_files"] = downloaded
    manifest["updated_utc"] = datetime.now(timezone.utc).isoformat()
    _summarize_rinex_availability(event, logical_stations, manifest, downloaded)
    manifest["stations_acquired"] = event.get("rinex_acquired_stations", [])
    manifest["stations_awaiting_archive"] = event.get("rinex_awaiting_archive", [])
    manifest["data_status"] = event.get("data_status")
    manifest_path = event_dir / "rinex_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    try:
        from retroactive_rinex import update_event_coverage_from_manifest

        update_event_coverage_from_manifest(event, manifest_path)
    except Exception as exc:
        log.debug("Could not update rinex_coverage fingerprint: %s", exc)
    log.info(f"  Total {downloaded} RINEX files in {event_dir}")
    return downloaded, str(event_dir)


def _summarize_rinex_availability(
    event: dict, logical_stations: list[str], manifest: dict, downloaded: int
) -> None:
    """Fields for dashboard: acquired vs still on NASA archive backlog."""
    acquired: set[str] = set()
    for day in manifest.get("days") or []:
        acquired.update(k.lower() for k in (day.get("resolved") or {}))
    requested = {s.lower() for s in logical_stations}
    awaiting = sorted(requested - acquired)
    acquired_sorted = sorted(acquired)
    event["rinex_acquired_stations"] = acquired_sorted
    event["rinex_awaiting_archive"] = awaiting
    if downloaded == 0:
        event["data_status"] = "awaiting_archive" if awaiting else "unavailable"
    elif awaiting:
        event["data_status"] = "partial"
    else:
        event["data_status"] = "ready"


def is_ready_to_download(event, force: bool = False):
    if force:
        return bool(event.get("usgs_id"))
    if event.get("retroactive_pending") and event.get("usgs_id"):
        return True
    if event.get("rinex_downloaded"):
        return False
    status = event.get("status", "")
    if status not in ("queued", "pending_rinex", "rinex_failed"):
        return False
    if status == "rinex_failed" and int(event.get("rinex_retries", 0)) >= 8:
        return False

    quake_time = datetime.fromisoformat(event["quake_utc"].replace("Z", "+00:00"))
    hours_since = (datetime.now(timezone.utc) - quake_time).total_seconds() / 3600
    window = event.get("detection_window") or {}
    min_wait_h = max(window.get("rinex_download_after_h", 3.0), 3.0)
    return hours_since >= min_wait_h


def _clear_running_log_score(usgs_id: str) -> None:
    p = Path("running_log.json")
    if not p.exists():
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        before = len(data.get("scored_events", []))
        data["scored_events"] = [
            e for e in data.get("scored_events", []) if e.get("usgs_id") != usgs_id
        ]
        if len(data["scored_events"]) < before:
            from scorer import update_summary

            update_summary(data)
            p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Could not trim running_log for %s: %s", usgs_id, e)


def reset_event_for_reprocess(event: dict, *, keep_retro_meta: bool = False) -> None:
    """Allow re-download + re-run detector on an already-processed event."""
    retro_meta = None
    if keep_retro_meta:
        retro_meta = {
            k: event.get(k)
            for k in (
                "retro_run_count",
                "retro_last_trigger_utc",
                "retro_trigger_reason",
                "retro_triggered_utc",
                "retro_prior_status",
                "retro_prior_prediction",
                "retro_prior_detected",
                "rinex_coverage_probe",
            )
            if event.get(k) is not None
        }
    _clear_running_log_score(event["usgs_id"])
    event["rinex_downloaded"] = False
    event["detector_run"] = False
    event["scored"] = False
    event.pop("prediction", None)
    event.pop("score", None)
    event.pop("discord_alerted", None)
    event["status"] = "queued"
    event["reprocess_requested"] = True
    if retro_meta:
        event.update(retro_meta)


def main(event_id=None, cache_only=False, force=False, skip_retro_check=False):
    log.info("=" * 55)
    log.info("GPS Tsunami Detector — RINEX Downloader")
    log.info("=" * 55)

    user, pwd = get_credentials()
    if not user:
        return []
    auth = HTTPBasicAuth(user, pwd)

    refresh_rolling_cache(auth)

    if cache_only:
        return []

    queue = load_queue()
    if not queue:
        return []

    retro_triggered: list[dict] = []
    if not force and not skip_retro_check and not event_id:
        try:
            from retroactive_rinex import find_retroactive_candidates

            retro_triggered = find_retroactive_candidates(queue["events"], auth)
            if retro_triggered:
                save_queue(queue)
                log.info("Retroactive: queued %d event(s) for re-download", len(retro_triggered))
        except Exception as exc:
            log.warning("Retroactive check skipped: %s", exc)

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]
        if not events:
            log.error(f"Event {event_id} not found")
            return

    if force:
        for event in events:
            reset_event_for_reprocess(event)
        save_queue(queue)
        log.info(f"Force reprocess: reset {len(events)} event(s)")

    ready = [e for e in events if is_ready_to_download(e, force=force)]
    log.info(f"Queue: {len(events)} events, {len(ready)} ready for event RINEX")

    if not ready:
        return retro_triggered

    for event in ready:
        count, event_dir = download_event(event, auth)
        if count > 0:
            event["rinex_downloaded"] = True
            event["rinex_dir"] = event_dir
            event["rinex_download_utc"] = datetime.now(timezone.utc).isoformat()
            event["status"] = "rinex_ready"
            event.pop("rinex_last_fail_utc", None)
            save_queue(queue)
            log.info(f"Updated queue: {event['usgs_id']} → rinex_ready ({count} files)")
        else:
            event["status"] = "rinex_failed"
            event["rinex_retries"] = int(event.get("rinex_retries", 0)) + 1
            event["rinex_last_fail_utc"] = datetime.now(timezone.utc).isoformat()
            if event.get("retroactive_pending"):
                event.pop("retroactive_pending", None)
            save_queue(queue)

    return retro_triggered


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Process specific USGS event ID")
    parser.add_argument("--cache-only", action="store_true", help="Only refresh rolling cache")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download RINEX and reset detector/scorer for selected event(s)",
    )
    args = parser.parse_args()
    main(event_id=args.event, cache_only=args.cache_only, force=args.force)
