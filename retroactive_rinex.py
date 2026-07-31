"""
Retroactive RINEX re-processing when CDDIS gains new station coverage.

Lightweight listing probes (no downloads) compare current CDDIS availability to the
last manifest / stored fingerprint. When coverage improves, the event is reset for
re-download + detector (+ scorer when 24h+ post-quake).
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from rinex_downloader import (
    EVENT_DOY_OFFSETS,
    discover_stations_near_epicenter,
    load_aliases,
    quake_to_doy,
    resolve_corridor_stations,
    save_aliases,
    stations_for_event,
)
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)

RETRO_MAX_AGE_DAYS = 21
RETRO_COOLDOWN_HOURS = 6
RETRO_MAX_PER_CYCLE = 2
RETRO_MAX_RUNS_PER_EVENT = 5
RETRO_ELIGIBLE_STATUSES = frozenset(
    {"predicted", "scored", "rinex_ready", "detector_failed", "rinex_failed"}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fingerprint_from_manifest(manifest_path: Path) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    stations: set[str] = set()
    days_out: list[dict] = []
    for day in manifest.get("days") or []:
        resolved = day.get("resolved") or {}
        st = {str(k).lower() for k in resolved}
        stations |= st
        days_out.append(
            {
                "year": day.get("year"),
                "doy": day.get("doy"),
                "stations": sorted(st),
                "n": len(st),
            }
        )
    return {
        "stations": sorted(stations),
        "n_stations": len(stations),
        "total_files": manifest.get("total_files"),
        "days": days_out,
        "source": "manifest",
    }


def probe_cddis_coverage(event: dict, sess, aliases: dict) -> dict[str, Any]:
    """Current resolvable station set on CDDIS (listing only)."""
    logical_stations = stations_for_event(event)
    _, _, _, quake_dt = quake_to_doy(event["quake_utc"])
    epi_lat, epi_lon = event.get("lat"), event.get("lon")

    all_stations: set[str] = set()
    days_out: list[dict] = []

    for day_off in EVENT_DOY_OFFSETS:
        dt = quake_dt + timedelta(days=day_off)
        year, doy, yr2 = dt.year, dt.timetuple().tm_yday, str(dt.year)[-2:]
        station_list = list(logical_stations)
        if epi_lat is not None and epi_lon is not None:
            for s in discover_stations_near_epicenter(
                epi_lat, epi_lon, year, doy, yr2, sess, aliases
            ):
                if s not in station_list:
                    station_list.append(s)

        resolved = resolve_corridor_stations(station_list, year, doy, yr2, sess, aliases)
        st = {k.lower() for k in resolved}
        all_stations |= st
        days_out.append(
            {"year": year, "doy": doy, "stations": sorted(st), "n": len(st)}
        )

    return {
        "stations": sorted(all_stations),
        "n_stations": len(all_stations),
        "days": days_out,
        "source": "probe",
        "probed_utc": _utcnow().isoformat(),
    }


def coverage_improvement(
    old: dict[str, Any] | None, new: dict[str, Any]
) -> tuple[bool, str]:
    """True if CDDIS can supply strictly more useful station coverage."""
    if not new or new.get("n_stations", 0) == 0:
        return False, ""

    new_set = set(new.get("stations") or [])
    if not old:
        return len(new_set) > 0, f"first coverage map: {', '.join(s.upper() for s in new_set)}"

    old_set = set(old.get("stations") or [])
    added = sorted(new_set - old_set)
    if added:
        return True, "new stations on CDDIS: " + ", ".join(s.upper() for s in added)

    old_days = {(d.get("year"), d.get("doy")): set(d.get("stations") or []) for d in old.get("days") or []}
    for day in new.get("days") or []:
        key = (day.get("year"), day.get("doy"))
        new_day_st = set(day.get("stations") or [])
        old_day_st = old_days.get(key, set())
        day_added = sorted(new_day_st - old_day_st)
        if day_added:
            doy = day.get("doy")
            return True, f"DOY {doy:03d} gained " + ", ".join(s.upper() for s in day_added)

    old_n = old.get("n_stations", len(old_set))
    new_n = new.get("n_stations", len(new_set))
    if new_n > old_n:
        return True, f"resolved station count {old_n} → {new_n}"

    return False, ""


def stored_fingerprint(event: dict) -> dict[str, Any] | None:
    if event.get("rinex_coverage"):
        return event["rinex_coverage"]
    rinex_dir = event.get("rinex_dir")
    if rinex_dir:
        return fingerprint_from_manifest(Path(rinex_dir) / "rinex_manifest.json")
    return fingerprint_from_manifest(
        Path("rinex_live") / event["usgs_id"] / "rinex_manifest.json"
    )


def is_eligible_for_retro_check(event: dict) -> bool:
    if not event.get("usgs_id"):
        return False
    if event.get("retroactive_pending"):
        return False
    if int(event.get("retro_run_count", 0)) >= RETRO_MAX_RUNS_PER_EVENT:
        return False

    status = event.get("status", "")
    if status not in RETRO_ELIGIBLE_STATUSES:
        return False

    quake = _parse_utc(event.get("quake_utc"))
    if not quake:
        return False
    age_days = (_utcnow() - quake).total_seconds() / 86400
    if age_days > RETRO_MAX_AGE_DAYS:
        return False

    last_trigger = _parse_utc(event.get("retro_last_trigger_utc"))
    if last_trigger:
        hours = (_utcnow() - last_trigger).total_seconds() / 3600
        if hours < RETRO_COOLDOWN_HOURS:
            return False

    return True


def queue_retroactive_reprocess(event: dict, reason: str, probe: dict) -> dict:
    """Annotate event for re-download without discarding the current result yet."""
    prior_prediction = deepcopy(event.get("prediction")) if event.get("prediction") else None
    prior_status = event.get("status")
    prior_detected = None
    if isinstance(prior_prediction, dict):
        prior_detected = prior_prediction.get("detected")

    event["retroactive_pending"] = True
    event["retroactive_trigger"] = True
    event["retro_trigger_reason"] = reason
    event["retro_triggered_utc"] = _utcnow().isoformat()
    event["retro_last_trigger_utc"] = event["retro_triggered_utc"]
    event["retro_run_count"] = int(event.get("retro_run_count", 0)) + 1
    event["retro_prior_status"] = prior_status
    event["retro_prior_prediction"] = prior_prediction
    event["retro_prior_detected"] = prior_detected
    event["rinex_coverage_probe"] = probe
    event["reprocess_requested"] = True

    return {
        "usgs_id": event["usgs_id"],
        "place": event.get("place"),
        "magnitude": event.get("magnitude"),
        "quake_utc": event.get("quake_utc"),
        "reason": reason,
        "prior_status": prior_status,
        "prior_detected": prior_detected,
        "new_stations": probe.get("stations"),
        "retro_run": event["retro_run_count"],
    }


def find_retroactive_candidates(
    events: list[dict], auth: HTTPBasicAuth
) -> list[dict]:
    """
    Probe CDDIS for processed events; return trigger payloads for those with improved coverage.
    Caps work per cycle via RETRO_MAX_PER_CYCLE.
    """
    from rinex_downloader import earthdata_session

    eligible = [e for e in events if is_eligible_for_retro_check(e)]
    if not eligible:
        return []

    # Prefer events with thinner coverage first (most likely to benefit).
    def sort_key(e: dict) -> tuple:
        fp = stored_fingerprint(e) or {}
        n = fp.get("n_stations", 0)
        quake = _parse_utc(e.get("quake_utc")) or _utcnow()
        age_h = (_utcnow() - quake).total_seconds() / 3600
        return (n, -age_h)

    eligible.sort(key=sort_key)

    sess = earthdata_session(auth)
    aliases = load_aliases()
    triggered: list[dict] = []

    for event in eligible:
        if len(triggered) >= RETRO_MAX_PER_CYCLE:
            break
        usgs_id = event["usgs_id"]
        try:
            probe = probe_cddis_coverage(event, sess, aliases)
            event["rinex_coverage_last_probe"] = probe
            event["retro_last_probe_utc"] = _utcnow().isoformat()

            old = stored_fingerprint(event)
            if not old:
                # Establish baseline without re-running (avoids one-time mass reprocess on deploy).
                event["rinex_coverage"] = probe
                log.debug(
                    "Retro baseline saved for %s (%d stations)",
                    usgs_id,
                    probe.get("n_stations", 0),
                )
                continue

            improved, reason = coverage_improvement(old, probe)
            if not improved:
                event["rinex_coverage_last_probe"] = probe
                continue

            log.info(
                "Retroactive reprocess queued: %s — %s (was %d stations, now %d)",
                usgs_id,
                reason,
                (old or {}).get("n_stations", 0),
                probe.get("n_stations", 0),
            )
            triggered.append(queue_retroactive_reprocess(event, reason, probe))
        except Exception as exc:
            log.warning("Retro probe failed for %s: %s", usgs_id, exc)

    save_aliases(aliases)
    return triggered


def update_event_coverage_from_manifest(event: dict, manifest_path: Path) -> None:
    fp = fingerprint_from_manifest(manifest_path)
    if fp:
        fp["updated_utc"] = _utcnow().isoformat()
        event["rinex_coverage"] = fp
