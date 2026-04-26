"""
USGS Earthquake Feed Listener
==============================
Polls the USGS real-time GeoJSON feed every 15 minutes.
Filters for Pacific subduction zone earthquakes above Mw 6.5.
Writes candidate events to event_queue.json for downstream processing.

Run continuously:
  python usgs_listener.py

Or as a one-shot check:
  python usgs_listener.py --once

Event queue file: event_queue.json
Log file: listener.log
"""

import json
import time
import logging
import argparse
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests")
    raise

# ── Config ─────────────────────────────────────────────────────────
POLL_INTERVAL_SEC = 900          # 15 minutes
MW_THRESHOLD      = 6.5          # minimum magnitude
LOOKBACK_HOURS    = 24           # how far back to look on startup
EVENT_QUEUE_FILE  = "event_queue.json"
POLL_LOG_FILE     = "poll_log.json"
LOG_FILE          = "listener.log"

# USGS feed — past 7 days, all magnitudes (we filter ourselves)
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_week.geojson"
USGS_FEED_ALL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"

# ── Pacific subduction zone bounding boxes ─────────────────────────
# Each zone has: name, lat_min, lat_max, lon_min, lon_max, upstream_anchor
# lon uses -180 to 180
PACIFIC_ZONES = [
    {
        "name": "Japan/Kuril",
        "lat": (30, 55), "lon": (130, 165),
        "anchor": "guam",
        "note": "Tōhoku, Kuril corridors → GUAM upstream"
    },
    {
        "name": "Alaska/Aleutian",
        "lat": (48, 62), "lon": (-180, -145),
        "anchor": "guam",
        "note": "Alaska corridor → GUAM or no anchor depending on geometry"
    },
    {
        "name": "Cascadia/BC",
        "lat": (40, 52), "lon": (-135, -120),
        "anchor": "guam",
        "note": "Haida Gwaii corridor → GUAM upstream"
    },
    {
        "name": "South America",
        "lat": (-45, -5), "lon": (-82, -65),
        "anchor": "chat",
        "note": "Chile/Peru corridor → CHAT (Chatham Islands) upstream"
    },
    {
        "name": "Tonga/Kermadec",
        "lat": (-35, -15), "lon": (-180, -172),
        "anchor": "thti",
        "note": "Tonga corridor → THTI (Tahiti) upstream"
    },
    {
        "name": "Vanuatu/Solomon",
        "lat": (-25, -5), "lon": (155, 180),
        "anchor": "guam",
        "note": "SW Pacific → GUAM or limited geometry"
    },
    {
        "name": "Sumatra/Andaman",
        "lat": (-5, 20), "lon": (90, 110),
        "anchor": None,
        "note": "Indian Ocean — geometry-limited for Hawaii detection"
    },
    {
        "name": "Central America",
        "lat": (5, 20), "lon": (-100, -82),
        "anchor": "chat",
        "note": "Central America → CHAT corridor possible"
    },
]

# Known false-positive source types (usually not tsunamigenic)
SKIP_TYPES = ["nuclear explosion", "quarry blast", "explosion", "mine collapse"]

# ── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(stream=__import__("sys").stdout)
    ]
)
import sys; sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────
def load_queue():
    if Path(EVENT_QUEUE_FILE).exists():
        return json.loads(Path(EVENT_QUEUE_FILE).read_text())
    return {"events": [], "seen_ids": []}

def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2))

def event_id(feature):
    """Stable ID from USGS event ID."""
    return feature["id"]

def in_pacific_zone(lat, lon):
    """Return matching zone(s) for a lat/lon, or empty list."""
    matches = []
    for zone in PACIFIC_ZONES:
        lat_ok = zone["lat"][0] <= lat <= zone["lat"][1]
        # Handle antimeridian crossing
        lo_min, lo_max = zone["lon"]
        if lo_min < lo_max:
            lon_ok = lo_min <= lon <= lo_max
        else:
            lon_ok = lon >= lo_min or lon <= lo_max
        if lat_ok and lon_ok:
            matches.append(zone)
    return matches

def haversine_km(la1, lo1, la2, lo2):
    import math
    R = 6371.0
    la1,lo1,la2,lo2 = map(math.radians,[la1,lo1,la2,lo2])
    dlat=la2-la1; dlon=lo2-lo1
    a=math.sin(dlat/2)**2+math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return R*2*math.asin(math.sqrt(a))

def estimate_detection_window(epi_lat, epi_lon, anchor):
    """Estimate expected TEC onset window at upstream anchor station."""
    ANCHOR_COORDS = {
        "guam": (13.489,  144.868),
        "chat": (-43.956, -176.566),
        "thti": (-17.577, -149.606),
        "mkea": (19.801,  -155.456),
    }
    HAWAII = (19.730, -155.087)  # Hilo

    if anchor not in ANCHOR_COORDS:
        return None

    anchor_lat, anchor_lon = ANCHOR_COORDS[anchor]
    dist_anchor = haversine_km(epi_lat, epi_lon, anchor_lat, anchor_lon)
    dist_hawaii = haversine_km(epi_lat, epi_lon, *HAWAII)

    # AGW travels ~200 m/s on average
    # TEC onset at anchor ≈ dist_anchor / 200 m/s
    onset_anchor_h = dist_anchor * 1000 / (200 * 3600)
    onset_hawaii_h = dist_hawaii * 1000 / (200 * 3600)

    # Add 30-min uncertainty either side
    return {
        "anchor": anchor,
        "anchor_dist_km": round(dist_anchor),
        "hawaii_dist_km": round(dist_hawaii),
        "tec_onset_anchor_h": round(onset_anchor_h, 1),
        "tec_onset_window": [
            round(onset_anchor_h - 0.5, 1),
            round(onset_anchor_h + 1.5, 1)
        ],
        "wave_arrival_hawaii_h": round(onset_hawaii_h, 1),
        "expected_lead_time_min": round((onset_hawaii_h - onset_anchor_h) * 60),
        "rinex_download_after_h": round(onset_anchor_h + 0.5, 1),
    }

def assess_event(feature):
    """
    Evaluate a USGS GeoJSON feature.
    Returns a candidate event dict or None if not relevant.
    """
    props = feature.get("properties", {})
    geom  = feature.get("geometry", {})

    mag   = props.get("mag")
    place = props.get("place", "")
    etype = props.get("type", "").lower()
    time_ms = props.get("time")
    coords = geom.get("coordinates", [None, None, None])

    if mag is None or mag < MW_THRESHOLD:
        return None
    if etype in SKIP_TYPES:
        return None
    if not coords or coords[0] is None:
        return None

    lon, lat, depth_km = coords[0], coords[1], coords[2] or 0

    # Depth filter — deep events (>100km) rarely tsunamigenic
    if depth_km > 100:
        log.debug(f"Skipping deep event: {place} depth={depth_km}km")
        return None

    # Fetch focal mechanism — fail-open (None = include by default)
    focal = fetch_focal_mechanism(feature["id"])
    tsunamigenic_index = None
    if focal and focal.get("available"):
        tsunamigenic_index = compute_tsunamigenic_index(focal["rake_score"], depth_km)
        if tsunamigenic_index < TSUNAMIGENIC_SKIP_THRESHOLD:
            log.info(
                f"  ShakeMap SKIP: {feature.get('id','')} "
                f"{focal['fault_type']} rake={focal['rake_deg']}° "
                f"index={tsunamigenic_index:.2f} < {TSUNAMIGENIC_SKIP_THRESHOLD}"
            )
            return None
        log.info(
            f"  ShakeMap OK: {focal['fault_type']} "
            f"rake={focal['rake_deg']}° index={tsunamigenic_index:.2f}"
        )
    else:
        log.debug(f"  ShakeMap: no focal data for {feature.get('id','')} — including")

    zones = in_pacific_zone(lat, lon)
    if not zones:
        return None

    quake_utc = datetime.fromtimestamp(time_ms/1000, tz=timezone.utc)
    anchor = zones[0].get("anchor")
    window = estimate_detection_window(lat, lon, anchor) if anchor else None

    event = {
        "usgs_id": feature["id"],
        "detected_utc": datetime.now(timezone.utc).isoformat(),
        "quake_utc": quake_utc.isoformat(),
        "magnitude": mag,
        "depth_km": round(depth_km, 1),
        "lat": round(lat, 3),
        "lon": round(lon, 3),
        "place": place,
        "zones": [z["name"] for z in zones],
        "primary_anchor": anchor,
        "anchor_note": zones[0].get("note", ""),
        "detection_window": window,
        "status": "queued",
        "rinex_downloaded": False,
        "detector_run": False,
        "scored": False,
        "result": None,
        "focal_mechanism": focal if focal else {"available": False},
        "tsunamigenic_index": tsunamigenic_index,
    }

    return event

def fetch_feed():
    """Fetch USGS feed, return list of features."""
    try:
        r = requests.get(USGS_FEED_ALL, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("features", [])
    except Exception as e:
        log.error(f"Feed fetch failed: {e}")
        return []



# ── ShakeMap focal mechanism filter ──────────────────────────
# Fetches USGS moment tensor data and scores tsunamigenic potential.
# Rake angle: +90=thrust (high), -90=normal (med), 0/180=strike-slip (low)

TSUNAMIGENIC_SKIP_THRESHOLD = 0.25  # below this = hard skip
FOCAL_TIMEOUT               = 12    # seconds per USGS detail API call


def classify_rake(rake_deg):
    """
    Convert rake angle to fault type and tsunamigenic score (0-1).
    +90 = pure thrust (1.0), -90 = normal (0.4), 0/180 = strike-slip (0.0-0.15)
    Returns (fault_type: str, score: float)
    """
    import math
    r = rake_deg % 360
    if r > 180: r -= 360
    abs_r = abs(r)
    if 45 <= abs_r <= 135:
        if r > 0:
            fault_type = "thrust"
            score = round(math.sin(math.radians(r)), 3)
        else:
            fault_type = "normal"
            score = round(0.4 * abs(math.sin(math.radians(r))), 3)
    else:
        fault_type = "strike-slip"
        score = round(0.15 * abs(math.sin(math.radians(r))), 3)
    return fault_type, max(0.0, min(1.0, score))


def compute_tsunamigenic_index(rake_score, depth_km):
    """
    Combine rake score with depth weighting.
    Shallow thrust events are most dangerous; deep events attenuate.
    """
    if depth_km is None or depth_km <= 30:
        depth_weight = 1.0
    elif depth_km <= 70:
        depth_weight = 0.7
    else:
        depth_weight = 0.4
    return round(rake_score * depth_weight, 3)


def fetch_focal_mechanism(usgs_id):
    """
    Fetch focal mechanism from USGS event detail API.
    Returns dict with rake, fault_type, tsunamigenic_score.
    Returns None on fetch failure (caller should fail-open).

    USGS product hierarchy: moment-tensor > focal-mechanism > beachball
    """
    url = f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{usgs_id}.geojson"
    try:
        r = requests.get(url, timeout=FOCAL_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.debug(f"  ShakeMap: fetch failed for {usgs_id}: {exc}")
        return None

    products = data.get("properties", {}).get("products", {})

    for ptype in ("moment-tensor", "focal-mechanism"):
        plist = products.get(ptype, [])
        if not plist:
            continue
        props = plist[0].get("properties", {})
        rake = None
        for plane in ("1", "2"):
            key = f"nodal-plane-{plane}-rake"
            if key in props:
                try:
                    rake = float(props[key])
                    break
                except (ValueError, TypeError):
                    continue
        if rake is None:
            continue
        fault_type, rake_score = classify_rake(rake)
        return {
            "rake_deg":          round(rake, 1),
            "fault_type":        fault_type,
            "rake_score":        rake_score,
            "product_type":      ptype,
            "source":            plist[0].get("source", "unknown"),
            "available":         True,
        }

    # No focal mechanism in USGS products yet (common for recent events)
    return {"available": False, "fault_type": "unknown",
            "rake_deg": None, "rake_score": 0.5, "product_type": None}


def check_feed(queue):
    """Check feed for new qualifying events. Returns (new_count, near_misses)."""
    features = fetch_feed()
    new_count = 0
    near_misses = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for feat in features:
        eid = event_id(feat)
        props = feat.get("properties", {})
        geom  = feat.get("geometry", {})
        mag   = props.get("mag")
        place = props.get("place", "Unknown")
        etype = props.get("type", "").lower()
        time_ms = props.get("time", 0)
        coords  = geom.get("coordinates", [None, None, None])

        if eid in queue["seen_ids"]:
            continue

        queue["seen_ids"].append(eid)

        if time_ms:
            event_time = datetime.fromtimestamp(time_ms/1000, tz=timezone.utc)
            if event_time < cutoff:
                continue
        else:
            event_time = datetime.now(timezone.utc)

        if mag is None or mag < 5.5:
            continue

        candidate = assess_event(feat)
        if candidate:
            queue["events"].append(candidate)
            new_count += 1
            w = candidate.get("detection_window") or {}
            log.info(
                f"NEW CANDIDATE: Mw{candidate['magnitude']} {candidate['place']} "
                f"zones={candidate['zones']} anchor={candidate['primary_anchor']} "
                f"TEC_window=+{w.get('tec_onset_window','?')}h "
                f"expected_lead={w.get('expected_lead_time_min','?')}min"
            )
        else:
            lon = coords[0] if coords and coords[0] is not None else None
            lat = coords[1] if coords and coords[1] is not None else None
            depth_km = coords[2] if coords and coords[2] is not None else 0

            if etype in SKIP_TYPES:
                reason = "non-tectonic"
                delta = None
            elif mag < MW_THRESHOLD:
                reason = "below threshold"
                delta = round(mag - MW_THRESHOLD, 1)
            elif depth_km and depth_km > 100:
                reason = f"too deep ({round(depth_km)}km)"
                delta = None
            elif etype not in SKIP_TYPES and mag >= MW_THRESHOLD:
                # Check focal mechanism for near-miss logging
                _fm = fetch_focal_mechanism(eid)
                if _fm and _fm.get("available"):
                    _ti = compute_tsunamigenic_index(_fm["rake_score"], depth_km or 0)
                    if _ti < TSUNAMIGENIC_SKIP_THRESHOLD:
                        reason = f"{_fm['fault_type']} (rake={_fm['rake_deg']}°)"
                        delta = None

            elif lat is not None and not in_pacific_zone(lat, lon):
                reason = "outside Pacific zones"
                delta = None
            else:
                reason = "filtered"
                delta = None

            near_misses.append({
                "ts":     event_time.isoformat(),
                "mag":    mag,
                "place":  place[:60],
                "lat":    round(lat, 2) if lat is not None else None,
                "lon":    round(lon, 2) if lon is not None else None,
                "depth":  round(depth_km, 1) if depth_km else None,
                "reason": reason,
                "delta":  delta,
            })

            if mag >= MW_THRESHOLD:
                log.debug(f"Skipped Mw{mag} {place} — {reason}")

    return new_count, near_misses

def print_status(queue):
    """Print current queue status."""
    events = queue["events"]
    if not events:
        log.info("Queue empty — no qualifying events yet")
        return

    log.info(f"Queue: {len(events)} events total")
    for ev in events[-5:]:  # show last 5
        w = ev.get("detection_window") or {}
        log.info(
            f"  {ev['quake_utc'][:16]}  Mw{ev['magnitude']}  {ev['place'][:40]}  "
            f"status={ev['status']}  anchor={ev['primary_anchor']}  "
            f"lead={w.get('expected_lead_time_min','?')}min"
        )

def write_poll_log(new_candidates, queue, near_misses=None):
    """Append a poll entry and near-miss events to poll_log.json."""
    poll_path = Path(POLL_LOG_FILE)
    if poll_path.exists():
        try:
            data = json.loads(poll_path.read_text())
        except Exception:
            data = {"total_polls": 0, "polls": [], "recent_seismicity": []}
    else:
        data = {"total_polls": 0, "polls": [], "recent_seismicity": []}

    if "recent_seismicity" not in data:
        data["recent_seismicity"] = []

    events = queue.get("events", [])
    scored = sum(1 for e in events if e.get("status") == "scored")

    entry = {
        "ts":             datetime.now(timezone.utc).isoformat(),
        "new_candidates": new_candidates,
        "total_queued":   len(events),
        "scored":         scored,
    }
    data["polls"].append(entry)
    data["total_polls"]  = len(data["polls"])
    data["last_updated"] = entry["ts"]

    # Append near-misses, keep last 100
    if near_misses:
        data["recent_seismicity"].extend(near_misses)
        data["recent_seismicity"] = data["recent_seismicity"][-100:]

    poll_path.write_text(json.dumps(data, indent=2))
    log.info(f"Poll log updated — total polls: {data['total_polls']}, "
             f"near-misses this cycle: {len(near_misses or [])}")


# ── Main ────────────────────────────────────────────────────────────
def main(once=False):
    log.info("="*55)
    log.info("GPS Tsunami Detector — USGS Feed Listener")
    log.info(f"Threshold: Mw>={MW_THRESHOLD}  Poll: {POLL_INTERVAL_SEC}s")
    log.info(f"Queue: {EVENT_QUEUE_FILE}")
    log.info("="*55)

    queue = load_queue()
    log.info(f"Loaded queue: {len(queue['events'])} existing events, "
             f"{len(queue['seen_ids'])} seen IDs")

    while True:
        log.info("Checking USGS feed...")
        new, near_misses = check_feed(queue)
        save_queue(queue)
        write_poll_log(new, queue, near_misses)

        if new > 0:
            log.info(f"Added {new} new candidate event(s)")
        else:
            log.info("No new qualifying events")

        print_status(queue)

        if once:
            log.info("--once mode, exiting")
            break

        log.info(f"Sleeping {POLL_INTERVAL_SEC}s until next check...")
        time.sleep(POLL_INTERVAL_SEC)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit instead of polling")
    args = parser.parse_args()
    main(once=args.once)
