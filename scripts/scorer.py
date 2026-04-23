"""
Automated Scorer
=================
Reads event_queue.json, finds events with predictions,
pulls NOAA tide gauge data 24h after the event,
scores prediction vs actual, and updates the log.

Run after detector_runner.py:
  python scorer.py

Scoring metrics:
  - Detection: hit / miss / false_alarm / no_anchor (correct abstention)
  - Lead time: predicted arrival vs actual gauge onset (minutes)
  - Amplitude error: predicted vs actual wave height (%)
  - Timing error: predicted TEC onset vs actual onset (minutes)

Output: scored events in event_queue.json
        running_log.json (append-only scoring record)
"""

import json
import logging
import argparse
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests"); raise

EVENT_QUEUE_FILE = "event_queue.json"
RUNNING_LOG_FILE = "running_log.json"
LOG_FILE         = "scorer.log"

NOAA_HILO_ID = "1617760"
NOAA_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def load_queue():
    if not Path(EVENT_QUEUE_FILE).exists(): return None
    return json.loads(Path(EVENT_QUEUE_FILE).read_text())

def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2))

def load_log():
    if Path(RUNNING_LOG_FILE).exists():
        return json.loads(Path(RUNNING_LOG_FILE).read_text())
    return {"scored_events": [], "summary": {}}

def save_log(log_data):
    Path(RUNNING_LOG_FILE).write_text(json.dumps(log_data, indent=2))

def fetch_tide_gauge(quake_utc_str, window_hours=48):
    """Fetch NOAA tide gauge data for Hilo around event time."""
    quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z","+00:00"))
    start_dt = quake_dt - timedelta(hours=2)
    end_dt   = quake_dt + timedelta(hours=window_hours)

    params = {
        "product": "water_level",
        "application": "gps_tsunami_detector",
        "begin_date": start_dt.strftime("%Y%m%d"),
        "end_date":   end_dt.strftime("%Y%m%d"),
        "datum": "MLLW",
        "station": NOAA_HILO_ID,
        "time_zone": "GMT",
        "units": "metric",
        "interval": "6",
        "format": "json"
    }

    try:
        r = requests.get(NOAA_API, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "data" not in data:
            log.warning(f"No tide data: {data.get('error', 'unknown')}")
            return None
        return data["data"]
    except Exception as e:
        log.error(f"Tide gauge fetch failed: {e}")
        return None

def parse_tide_tsunami(tide_data, quake_utc_str):
    """
    Detect tsunami onset in tide gauge data.
    Returns (onset_utc, amplitude_m, arrival_h_post_quake) or None.
    """
    if not tide_data:
        return None

    quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z","+00:00"))

    # Parse time series
    times = []
    vals  = []
    flags = []
    for rec in tide_data:
        try:
            t = datetime.strptime(rec["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            v = float(rec["v"])
            f = rec.get("f","0,0,0,0")
            times.append(t)
            vals.append(v)
            flags.append(f)
        except: continue

    if len(times) < 10:
        return None

    # Simple tsunami detection: look for NOAA flag bits or anomalous variance
    # NOAA flags "0,0,1,0" = exceeds expected range (tsunami oscillation)
    tsunami_times = [t for t,f in zip(times,flags) if "0,0,1,0" in f]

    if tsunami_times:
        first_arrival = min(tsunami_times)
        arrival_h = (first_arrival - quake_dt).total_seconds() / 3600

        # Only accept arrivals in realistic tsunami window (2-20h)
        if not (2.0 <= arrival_h <= 20.0):
            tsunami_times = []

    if tsunami_times:
        first_arrival = min(tsunami_times)
        arrival_h = (first_arrival - quake_dt).total_seconds() / 3600

        # Amplitude: peak-to-trough/2 in 2h window after arrival
        window_start = first_arrival
        window_end   = first_arrival + timedelta(hours=2)
        window_vals  = [v for t,v in zip(times,vals)
                       if window_start <= t <= window_end]
        if window_vals:
            amp = (max(window_vals) - min(window_vals)) / 2
        else:
            amp = 0.0

        return {
            "onset_utc": first_arrival.isoformat(),
            "arrival_h_post_quake": round(arrival_h, 2),
            "amplitude_m": round(amp, 3),
            "detection_method": "noaa_flag",
        }

    # Fallback: variance-based detection
    import numpy as np
    pre_window = [v for t,v in zip(times,vals)
                 if (t-quake_dt).total_seconds()/3600 < 1.5]
    if pre_window:
        baseline_std = np.std(pre_window)
        baseline_mean = np.mean(pre_window)
        threshold = baseline_mean + 3 * baseline_std

        for t,v in zip(times,vals):
            h = (t-quake_dt).total_seconds()/3600
            if 2.0 <= h <= 20.0 and abs(v-baseline_mean) > 3*baseline_std:
                # Potential tsunami signal
                window_vals = [vv for tt,vv in zip(times,vals)
                               if t <= tt <= t+timedelta(hours=2)]
                amp = (max(window_vals)-min(window_vals))/2 if window_vals else 0
                if amp > 0.05:  # minimum detectable amplitude
                    return {
                        "onset_utc": t.isoformat(),
                        "arrival_h_post_quake": round(h, 2),
                        "amplitude_m": round(amp, 3),
                        "detection_method": "variance_threshold",
                    }

    return None  # No tsunami detected at Hilo

def score_event(event, tide_tsunami):
    """
    Score a single prediction against gauge truth.
    Returns a score dict.
    """
    pred = event.get("prediction", {})
    detected_by_algo = pred.get("detected", False)
    anchor = event.get("primary_anchor")

    score = {
        "usgs_id": event["usgs_id"],
        "quake_utc": event["quake_utc"],
        "magnitude": event["magnitude"],
        "place": event["place"],
        "anchor": anchor,
        "kp": pred.get("kp"),
        "algo_detected": detected_by_algo,
        "gauge_tsunami": tide_tsunami is not None,
        "outcome": None,
        "lead_time_min": None,
        "amplitude_predicted_m": None,
        "amplitude_actual_m": None,
        "amplitude_error_pct": None,
        "timing_error_min": None,
        "notes": [],
    }

    # Determine outcome
    if detected_by_algo and tide_tsunami:
        score["outcome"] = "TRUE_POSITIVE"
    elif not detected_by_algo and not tide_tsunami:
        if not anchor:
            score["outcome"] = "CORRECT_ABSTENTION_NO_ANCHOR"
        else:
            score["outcome"] = "TRUE_NEGATIVE"
    elif detected_by_algo and not tide_tsunami:
        score["outcome"] = "FALSE_POSITIVE"
    elif not detected_by_algo and tide_tsunami:
        if not anchor:
            score["outcome"] = "GEOMETRY_LIMITED_MISS"
        else:
            score["outcome"] = "FALSE_NEGATIVE"

    # Quantitative scores for true positives
    if tide_tsunami and detected_by_algo:
        det = pred.get("detection", {})
        wf  = pred.get("wave_forecast", {})

        # Lead time
        algo_onset_h = det.get("post_h", 0)
        actual_arrival_h = tide_tsunami["arrival_h_post_quake"]
        score["lead_time_min"] = round((actual_arrival_h - algo_onset_h) * 60)

        # Amplitude
        if wf and "predicted_wave_m" in wf:
            score["amplitude_predicted_m"] = wf["predicted_wave_m"]
            score["amplitude_actual_m"]    = tide_tsunami["amplitude_m"]
            if tide_tsunami["amplitude_m"] > 0:
                score["amplitude_error_pct"] = round(
                    (wf["predicted_wave_m"] - tide_tsunami["amplitude_m"]) /
                    tide_tsunami["amplitude_m"] * 100, 1
                )

    if tide_tsunami:
        score["tide_gauge_truth"] = tide_tsunami

    return score

def update_summary(log_data):
    """Recompute running summary statistics."""
    events = log_data["scored_events"]
    if not events:
        return

    outcomes = [e.get("outcome") for e in events if e.get("outcome")]
    tp = outcomes.count("TRUE_POSITIVE")
    tn = outcomes.count("TRUE_NEGATIVE") + outcomes.count("CORRECT_ABSTENTION_NO_ANCHOR")
    fp = outcomes.count("FALSE_POSITIVE")
    fn = outcomes.count("FALSE_NEGATIVE") + outcomes.count("GEOMETRY_LIMITED_MISS")

    lead_times = [e["lead_time_min"] for e in events
                  if e.get("lead_time_min") is not None]
    amp_errors = [abs(e["amplitude_error_pct"]) for e in events
                  if e.get("amplitude_error_pct") is not None]

    log_data["summary"] = {
        "total_scored": len(events),
        "true_positives": tp,
        "true_negatives": tn,
        "false_positives": fp,
        "false_negatives": fn,
        "tpr": round(tp/(tp+fn), 3) if (tp+fn) > 0 else None,
        "fpr": round(fp/(fp+tn), 3) if (fp+tn) > 0 else None,
        "mean_lead_time_min": round(np.mean(lead_times), 1) if lead_times else None,
        "median_lead_time_min": round(np.median(lead_times), 1) if lead_times else None,
        "mean_amplitude_error_pct": round(np.mean(amp_errors), 1) if amp_errors else None,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }

def is_ready_to_score(event):
    """Check if event is ready for scoring (prediction done + 24h+ elapsed)."""
    if event.get("scored"): return False
    if event.get("status") != "predicted": return False

    quake_time = datetime.fromisoformat(event["quake_utc"].replace("Z","+00:00"))
    hours_since = (datetime.now(timezone.utc) - quake_time).total_seconds() / 3600
    return hours_since >= 24.0

def main(event_id=None, force=False):
    log.info("="*55)
    log.info("GPS Tsunami Detector — Scorer")
    log.info("="*55)

    queue = load_queue()
    if not queue: return

    log_data = load_log()
    already_scored = {e["usgs_id"] for e in log_data["scored_events"]}

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]

    ready = [e for e in events
             if (is_ready_to_score(e) or force) and e["usgs_id"] not in already_scored]

    log.info(f"Events ready to score: {len(ready)}")

    for event in ready:
        log.info(f"\nScoring: {event['usgs_id']}  {event['place']}  Mw{event['magnitude']}")

        # Fetch tide gauge
        tide_data = fetch_tide_gauge(event["quake_utc"])
        tide_tsunami = parse_tide_tsunami(tide_data, event["quake_utc"])

        if tide_tsunami:
            log.info(f"  Tide gauge: tsunami detected at +{tide_tsunami['arrival_h_post_quake']:.1f}h, "
                     f"amplitude={tide_tsunami['amplitude_m']:.3f}m")
        else:
            log.info(f"  Tide gauge: no tsunami signal at Hilo")

        # Score
        score = score_event(event, tide_tsunami)
        log.info(f"  Outcome: {score['outcome']}")
        if score.get("lead_time_min") is not None:
            log.info(f"  Lead time: {score['lead_time_min']} min")
        if score.get("amplitude_error_pct") is not None:
            log.info(f"  Amplitude error: {score['amplitude_error_pct']:+.0f}%")

        # Update queue
        event["scored"] = True
        event["score"] = score
        event["status"] = "scored"
        event["scored_utc"] = datetime.now(timezone.utc).isoformat()

        # Append to running log
        log_data["scored_events"].append(score)
        update_summary(log_data)
        save_queue(queue)
        save_log(log_data)
        log.info(f"  Updated log: {RUNNING_LOG_FILE}")

    # Print running summary
    if log_data["scored_events"]:
        s = log_data["summary"]
        log.info(f"\n{'='*55}")
        log.info(f"RUNNING SUMMARY  ({s['total_scored']} events scored)")
        log.info(f"  TP={s['true_positives']}  TN={s['true_negatives']}  "
                 f"FP={s['false_positives']}  FN={s['false_negatives']}")
        if s['tpr'] is not None:
            log.info(f"  TPR={s['tpr']:.3f}  FPR={s['fpr']:.3f}")
        if s['mean_lead_time_min'] is not None:
            log.info(f"  Lead time: mean={s['mean_lead_time_min']}min  "
                     f"median={s['median_lead_time_min']}min")
        if s['mean_amplitude_error_pct'] is not None:
            log.info(f"  Amplitude error: {s['mean_amplitude_error_pct']:.1f}% mean absolute")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Score specific USGS event ID")
    parser.add_argument("--force", action="store_true",
                        help="Score even if <24h elapsed")
    args = parser.parse_args()
    main(event_id=args.event, force=args.force)
