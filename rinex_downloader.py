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
LOG_FILE = "downloader.log"
CDDIS_BASE = "https://cddis.nasa.gov/archive/gnss/data/daily"
CDDIS_SUFFIXES = (".gz", ".Z")
CACHE_DAYS = 2  # today + yesterday UTC

CORRIDOR_STATIONS = {
    "guam": ["guam", "kwj1", "noum", "holb", "mkea", "kokb", "hnlc"],
    "chat": ["chat", "auck", "mkea", "kokb", "hnlc"],
    "thti": ["thti", "thtg", "auck", "noum", "mkea", "kokb"],
    None: ["mkea", "kokb", "hnlc", "guam"],
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
    return sorted(seen)


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


def download_event(event, auth: HTTPBasicAuth):
    year, doy, yr2, quake_dt = quake_to_doy(event["quake_utc"])
    anchor = event.get("primary_anchor")
    logical_stations = CORRIDOR_STATIONS.get(anchor, CORRIDOR_STATIONS[None])

    event_dir = Path(RINEX_BASE_DIR) / event["usgs_id"]
    event_dir.mkdir(parents=True, exist_ok=True)
    sess = earthdata_session(auth)
    aliases = load_aliases()

    log.info(f"\nRINEX for {event['usgs_id']} — {event.get('place', '')[:50]}")
    log.info(f"  Mw{event['magnitude']}  {event['quake_utc'][:16]}  DOY={doy}")

    resolved = resolve_corridor_stations(logical_stations, year, doy, yr2, sess, aliases)
    downloaded = copy_from_cache(year, doy, yr2, resolved, event_dir)
    log.info(f"  From cache: {downloaded} files")

    for logical, code in resolved.items():
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

    if quake_dt.hour >= 18:
        next_dt = quake_dt + timedelta(days=1)
        ny, ndoy, ny2 = next_dt.year, next_dt.timetuple().tm_yday, str(next_dt.year)[-2:]
        log.info(f"  Late UTC — adding DOY {ndoy}")
        resolved_next = resolve_corridor_stations(
            logical_stations[:4], ny, ndoy, ny2, sess, aliases
        )
        downloaded += copy_from_cache(ny, ndoy, ny2, resolved_next, event_dir)
        for logical, code in resolved_next.items():
            downloaded += download_station_day_to_dir(
                ny, ndoy, ny2, code, event_dir, sess
            )

    save_aliases(aliases)
    log.info(f"  Total {downloaded} RINEX files in {event_dir}")
    return downloaded, str(event_dir)


def is_ready_to_download(event):
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


def main(event_id=None, cache_only=False):
    log.info("=" * 55)
    log.info("GPS Tsunami Detector — RINEX Downloader")
    log.info("=" * 55)

    user, pwd = get_credentials()
    if not user:
        return
    auth = HTTPBasicAuth(user, pwd)

    refresh_rolling_cache(auth)

    if cache_only:
        return

    queue = load_queue()
    if not queue:
        return

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]
        if not events:
            log.error(f"Event {event_id} not found")
            return

    ready = [e for e in events if is_ready_to_download(e)]
    log.info(f"Queue: {len(events)} events, {len(ready)} ready for event RINEX")

    if not ready:
        return

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
            save_queue(queue)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Process specific USGS event ID")
    parser.add_argument("--cache-only", action="store_true", help="Only refresh rolling cache")
    args = parser.parse_args()
    main(event_id=args.event, cache_only=args.cache_only)
