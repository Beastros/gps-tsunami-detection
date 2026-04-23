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

def check_feed(queue):
    """Check feed for new qualifying events, add to queue."""
    features = fetch_feed()
    new_count = 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for feat in features:
        eid = event_id(feat)
        if eid in queue["seen_ids"]:
            continue

        queue["seen_ids"].append(eid)

        # Age filter
        time_ms = feat.get("properties", {}).get("time", 0)
        if time_ms:
            event_time = datetime.fromtimestamp(time_ms/1000, tz=timezone.utc)
            if event_time < cutoff:
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
            # Log why skipped for transparency
            props = feat.get("properties", {})
            mag = props.get("mag", 0)
            if mag and mag >= MW_THRESHOLD:
                coords = feat.get("geometry", {}).get("coordinates", [])
                if coords:
                    log.debug(
                        f"Skipped Mw{mag} {props.get('place','')} "
                        f"lat={coords[1]:.1f} lon={coords[0]:.1f} "
                        f"(not Pacific subduction or too deep)"
                    )

    return new_count

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
        new = check_feed(queue)
        save_queue(queue)

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
