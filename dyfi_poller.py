"""
dyfi_poller.py -- DYFI shake ping poller for dashboard map
GPS Ionospheric Tsunami Detection Pipeline -- V8

Polls USGS for recent Mw5.0+ Pacific events with DYFI felt reports.
Writes dyfi_pings.json to the repo folder for the dashboard map.
Runs every pipeline cycle independent of the Mw6.5+ detection gate.

Pacific basin covered via two USGS queries (avoids antimeridian issue):
  Western: lon 100 to 180, lat -65 to 65
  Eastern: lon -180 to -60, lat -65 to 65

The USGS summary feed already includes 'felt' (DYFI response count) and
'mmi' (max Modified Mercalli Intensity) -- no per-event detail call needed.
"""
import os
import json
import logging
import requests
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

REPO_DIR = r"C:\Users\Mike\Desktop\repo"
OUTPUT   = os.path.join(REPO_DIR, "dyfi_pings.json")

USGS_URL = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson&orderby=time&limit=50"
    "&minmagnitude=5.0"
    "&starttime={starttime}"
    "&minlatitude=-65&maxlatitude=65"
    "&minlongitude={minlon}&maxlongitude={maxlon}"
)

PACIFIC_BOXES = [
    ("western",  100,  180),
    ("eastern", -180,  -60),
]

MIN_FELT     = 10   # minimum felt reports to appear on map
LOOKBACK_HRS = 12   # hours of history shown


def run():
    """
    Fetch Pacific felt events from USGS and write dyfi_pings.json.
    Fail-open: any error writes an empty pings file so dashboard gets no 404.
    Returns list of ping dicts written.
    """
    try:
        starttime = (
            datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HRS)
        ).strftime("%Y-%m-%dT%H:%M:%S")

        seen = {}
        for name, minlon, maxlon in PACIFIC_BOXES:
            url = USGS_URL.format(starttime=starttime, minlon=minlon, maxlon=maxlon)
            try:
                r = requests.get(url, timeout=15)
                if r.status_code != 200:
                    log.warning("DYFI poller %s HTTP %d", name, r.status_code)
                    continue
                for feat in r.json().get("features", []):
                    eid = feat["id"]
                    if eid not in seen:
                        seen[eid] = feat
            except Exception as e:
                log.warning("DYFI poller %s error: %s", name, e)

        pings = []
        for feat in seen.values():
            props  = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [])
            felt   = props.get("felt")
            if not felt or felt < MIN_FELT:
                continue
            mag = props.get("mag")
            mmi = props.get("mmi")
            if mag is None or len(coords) < 2:
                continue
            pings.append({
                "usgs_id":        feat["id"],
                "mag":            round(float(mag), 1),
                "place":          props.get("place", "Unknown location"),
                "time_ms":        props.get("time", 0),
                "lat":            round(float(coords[1]), 3),
                "lon":            round(float(coords[0]), 3),
                "depth":          round(float(coords[2]), 1) if len(coords) > 2 else None,
                "dyfi_responses": int(felt),
                "dyfi_maxmmi":    round(float(mmi), 1) if mmi is not None else None,
            })

        pings.sort(key=lambda x: x["time_ms"], reverse=True)
        out = {
            "generated":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lookback_hrs": LOOKBACK_HRS,
            "count":        len(pings),
            "pings":        pings,
        }
        with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=2)
        log.info("DYFI poller: %d pings written", len(pings))
        return pings

    except Exception as e:
        log.warning("DYFI poller exception: %s -- fail open", e)
        try:
            out = {
                "generated":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "lookback_hrs": LOOKBACK_HRS,
                "count":        0,
                "pings":        [],
            }
            with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
                json.dump(out, f, indent=2)
        except Exception:
            pass
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pings = run()
    print(f"Found {len(pings)} DYFI pings:")
    for p in pings:
        print(f"  M{p['mag']} {p['place']} -- {p['dyfi_responses']} felt, MMI {p['dyfi_maxmmi']}")
