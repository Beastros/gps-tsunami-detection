"""
ionosonde_checker.py — GIRO Digisonde foF2 cross-check
==========================================================
Fetches foF2 (F2-layer critical frequency) data from the GIRO
DIDBase network and detects co-seismic ionospheric perturbations
independent of GPS.

Why this matters:
  GPS TEC measures electron content along slant paths to satellites.
  Digisondes measure the F2 plasma frequency vertically using HF radar.
  These are completely different instruments, different physics, different
  geometry. Agreement between GPS TEC anomaly and Digisonde foF2 anomaly
  is extremely strong evidence of a real ionospheric disturbance.

Data source: GIRO DIDBase — free, no authentication required
  https://giro.uml.edu/didbase/

Pacific stations used:
  GU513  Guam           13.6N 144.9E  (co-located with GPS GUAM station)
  KJ609  Kwajalein       9.0N 167.7E  (Marshall Islands, central Pacific)
  WP937  Wake Island    19.3N 166.6E  (north-central Pacific)
  RP536  Okinawa        26.7N 128.2E  (western Pacific)
  AT138  Townsville     19.6S 146.8E  (Australia, covers SW Pacific)

Run standalone:
  python ionosonde_checker.py --quake-utc 2011-03-11T05:46:24Z --lat 38.3 --lon 142.4
"""

import json
import logging
import math
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# ── Station network ───────────────────────────────────────────────
IONOSONDE_STATIONS = {
    "GU513": {"lat":  13.6, "lon":  144.9, "name": "Guam",         "realtime": True},
    "KJ609": {"lat":   9.0, "lon":  167.7, "name": "Kwajalein",    "realtime": True},
    "WP937": {"lat":  19.3, "lon":  166.6, "name": "Wake Island",  "realtime": False},
    "RP536": {"lat":  26.7, "lon":  128.2, "name": "Okinawa",      "realtime": True},
    "AT138": {"lat": -19.6, "lon":  146.8, "name": "Townsville",   "realtime": True},
    "TW637": {"lat":  25.0, "lon":  121.2, "name": "Zhongli",      "realtime": True},
    "CH853": {"lat": -43.9, "lon": -176.6, "name": "Chatham Is.",  "realtime": False},
}

# GIRO DIDBase API
GIRO_API  = "https://giro.uml.edu/didbase/scaled.php"
TIMEOUT   = 20   # seconds per station

# Detection parameters
BASELINE_H       = 2.0   # hours pre-quake for baseline
MIN_ARRIVAL_H    = 1.5   # earliest realistic AGW arrival at ionosonde
MAX_ARRIVAL_H    = 20.0  # latest realistic arrival
SIGMA_THRESHOLD  = 2.5   # foF2 anomaly threshold (lower than DART — coarser data)
MIN_DELTA_FOF2   = 0.15  # MHz — minimum detectable perturbation
MAX_STATION_KM   = 6000  # maximum station distance from epicenter

# foF2 perturbation from tsunami-driven AGW is typically 0.2–1.0 MHz
# above a baseline that varies from 3–12 MHz depending on time of day/lat


def haversine_km(la1, lo1, la2, lo2):
    R = 6371.0
    la1, lo1, la2, lo2 = map(math.radians, [la1, lo1, la2, lo2])
    dlat = la2 - la1
    dlon = lo2 - lo1
    a = math.sin(dlat/2)**2 + math.cos(la1)*math.cos(la2)*math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def select_stations(epi_lat, epi_lon, max_dist_km=MAX_STATION_KM):
    """Select ionosonde stations within range of epicenter, sorted by distance."""
    candidates = []
    for ursi, cfg in IONOSONDE_STATIONS.items():
        dist = haversine_km(epi_lat, epi_lon, cfg["lat"], cfg["lon"])
        if dist <= max_dist_km:
            candidates.append({
                "ursi":     ursi,
                "name":     cfg["name"],
                "lat":      cfg["lat"],
                "lon":      cfg["lon"],
                "dist_km":  round(dist),
                "realtime": cfg["realtime"],
            })
    candidates.sort(key=lambda x: x["dist_km"])
    return candidates


def fetch_fof2(ursi_code, quake_dt, hours_before=3, hours_after=22):
    """
    Fetch foF2 time series from GIRO DIDBase.

    Returns list of (datetime, fof2_mhz) tuples or None on failure.
    GIRO returns autoscaled ionogram-derived foF2 at 15-minute cadence.
    """
    start_dt = quake_dt - timedelta(hours=hours_before)
    end_dt   = quake_dt + timedelta(hours=hours_after)

    params = {
        "ursiCode":  ursi_code,
        "charName":  "foF2",
        "YYYY":      start_dt.strftime("%Y"),
        "MM":        start_dt.strftime("%m"),
        "DD":        start_dt.strftime("%d"),
        "hh":        start_dt.strftime("%H"),
        "mm":        start_dt.strftime("%M"),
        "Dres":      15,          # 15-minute resolution
        "dataflag":  0,           # autoscaled data
        "isDesc":    0,
        "fmt":       "json",
    }

    # Compute number of records needed
    total_minutes = int((hours_before + hours_after) * 60)
    params["nRecords"] = total_minutes // 15 + 4

    try:
        r = requests.get(GIRO_API, params=params, timeout=TIMEOUT,
                         headers={"User-Agent": "gps-tsunami-detector"})
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        log.debug(f"  GIRO fetch failed for {ursi_code}: {exc}")
        return None

    # Parse GIRO JSON response
    # Format varies: may be {"Records": [...]} or direct array
    records_raw = None
    if isinstance(data, dict):
        records_raw = data.get("Records") or data.get("records") or data.get("data")
    elif isinstance(data, list):
        records_raw = data

    if not records_raw:
        log.debug(f"  GIRO {ursi_code}: empty response")
        return None

    series = []
    for rec in records_raw:
        try:
            # GIRO format: {"time": "2011-03-11T05:00:00Z", "foF2": "8.45", ...}
            # or positional list [timestamp, foF2, ...]
            if isinstance(rec, dict):
                ts_raw  = rec.get("time") or rec.get("ts") or rec.get("Time")
                val_raw = rec.get("foF2") or rec.get("fof2") or rec.get("value")
            elif isinstance(rec, (list, tuple)) and len(rec) >= 2:
                ts_raw  = rec[0]
                val_raw = rec[1]
            else:
                continue

            if ts_raw is None or val_raw is None:
                continue

            # Parse timestamp
            ts_str = str(ts_raw).replace(" ", "T")
            if not ts_str.endswith("Z") and "+" not in ts_str:
                ts_str += "Z"
            t = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

            fof2 = float(val_raw)
            if fof2 <= 0 or fof2 > 25:  # sanity check (foF2 range 1-18 MHz typical)
                continue

            series.append((t, fof2))
        except Exception:
            continue

    return series if series else None


def detect_fof2_anomaly(series, quake_dt, dist_km):
    """
    Detect foF2 perturbation in the post-quake detection window.

    Tsunami-driven atmospheric gravity waves perturb the F2 layer,
    causing foF2 changes of 0.2-1.0 MHz above background.

    Returns detection dict or None.
    """
    if not series or len(series) < 4:
        return None

    # Pre-quake baseline
    baseline_start = quake_dt - timedelta(hours=BASELINE_H + 0.5)
    baseline_end   = quake_dt
    baseline_vals  = [f for t, f in series if baseline_start <= t <= baseline_end]

    if len(baseline_vals) < 2:
        log.debug(f"    Insufficient baseline ({len(baseline_vals)} points)")
        return None

    import statistics
    baseline_mean = statistics.mean(baseline_vals)
    baseline_std  = max(statistics.stdev(baseline_vals) if len(baseline_vals) > 1 else 0.1, 0.05)
    threshold     = SIGMA_THRESHOLD * baseline_std

    # Detection window
    window_start = quake_dt + timedelta(hours=MIN_ARRIVAL_H)
    window_end   = quake_dt + timedelta(hours=MAX_ARRIVAL_H)

    # Expected AGW arrival (speed ~200 m/s average)
    expected_h = dist_km * 1000 / (200 * 3600)

    candidates = []
    for t, f in series:
        if window_start <= t <= window_end:
            delta = abs(f - baseline_mean)
            if delta >= threshold and delta >= MIN_DELTA_FOF2:
                arrival_h = (t - quake_dt).total_seconds() / 3600
                candidates.append((t, f, delta, arrival_h))

    if not candidates:
        return None

    # Take earliest candidate as onset
    onset_dt, onset_f, onset_delta, onset_h = candidates[0]

    # Peak perturbation in 2h after onset
    amp_end  = onset_dt + timedelta(hours=2)
    amp_vals = [f for t, f in series if onset_dt <= t <= amp_end]
    if amp_vals:
        peak_delta = max(abs(f - baseline_mean) for f in amp_vals)
    else:
        peak_delta = onset_delta

    return {
        "onset_utc":              onset_dt.isoformat(),
        "arrival_h_post_quake":   round(onset_h, 2),
        "expected_arrival_h":     round(expected_h, 1),
        "arrival_error_h":        round(onset_h - expected_h, 1),
        "fof2_baseline_mhz":      round(baseline_mean, 3),
        "fof2_baseline_std_mhz":  round(baseline_std, 4),
        "fof2_delta_mhz":         round(peak_delta, 3),
        "fof2_sigma":             round(peak_delta / baseline_std, 1),
        "detection_method":       "fof2_sigma_threshold",
    }


def check_ionosonde_network(quake_utc_str, epi_lat, epi_lon):
    """
    Main entry point. Check all relevant Digisonde stations for co-seismic
    ionospheric perturbations.

    Returns dict: {
      "stations_checked":  int,
      "stations_with_data": int,
      "ionosonde_detected": bool,
      "confirming_stations": int,
      "results": { ursi: { ... } }
    }
    """
    quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))
    stations = select_stations(epi_lat, epi_lon)

    if not stations:
        log.info("  IONOSONDE: No stations within range of epicenter")
        return {
            "stations_checked":    0,
            "stations_with_data":  0,
            "ionosonde_detected":  False,
            "confirming_stations": 0,
            "results": {},
        }

    log.info(f"  IONOSONDE: Checking {len(stations)} stations")

    results      = {}
    confirming   = 0
    with_data    = 0

    for sta in stations:
        ursi = sta["ursi"]
        name = sta["name"]
        dist = sta["dist_km"]

        log.info(f"    {ursi} ({name}) — {dist} km from epicenter")

        series = fetch_fof2(ursi, quake_dt)

        if not series:
            results[ursi] = {
                "name":      name,
                "dist_km":   dist,
                "lat":       sta["lat"],
                "lon":       sta["lon"],
                "data":      False,
                "detected":  False,
                "detection": None,
            }
            continue

        with_data += 1
        detection  = detect_fof2_anomaly(series, quake_dt, dist)

        if detection:
            confirming += 1
            log.info(
                f"      → foF2 SIGNAL: +{detection['arrival_h_post_quake']:.1f}h "
                f"delta={detection['fof2_delta_mhz']:.2f} MHz "
                f"({detection['fof2_sigma']:.1f}σ)"
            )
        else:
            log.info(f"      → No signal")

        results[ursi] = {
            "name":      name,
            "dist_km":   dist,
            "lat":       sta["lat"],
            "lon":       sta["lon"],
            "data":      True,
            "detected":  detection is not None,
            "detection": detection,
        }

    ionosonde_detected = confirming >= 1

    summary = {
        "stations_checked":    len(stations),
        "stations_with_data":  with_data,
        "ionosonde_detected":  ionosonde_detected,
        "confirming_stations": confirming,
        "nearest_station_km":  stations[0]["dist_km"] if stations else None,
        "results":             results,
    }

    if ionosonde_detected:
        log.info(
            f"  IONOSONDE SUMMARY: Confirmed by {confirming}/{with_data} "
            f"stations with data"
        )
    else:
        log.info(
            f"  IONOSONDE SUMMARY: No signal ({with_data} stations with data)"
        )

    return summary


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")

    parser = argparse.ArgumentParser(description="GIRO Digisonde foF2 anomaly checker")
    parser.add_argument("--quake-utc", required=True, help="Quake UTC ISO string")
    parser.add_argument("--lat",  type=float, required=True, help="Epicenter latitude")
    parser.add_argument("--lon",  type=float, required=True, help="Epicenter longitude")
    args = parser.parse_args()

    result = check_ionosonde_network(args.quake_utc, args.lat, args.lon)
    print(json.dumps(result, indent=2, default=str))
