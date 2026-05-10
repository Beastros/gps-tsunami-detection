"""
Automated Scorer
=================
Reads event_queue.json, finds events with predictions,
pulls NOAA tide gauge data 24h after the event,
scores prediction vs actual, and updates the log.

Run after detector_runner.py:
  python scorer.py

Scoring layers:
  Layer 1 (binary):      TEC detected → TRUE_POSITIVE / FALSE_POSITIVE / etc.
  Layer 2 (confidence):  combined_confidence threshold → confidence_detected
  Layer 3 (calibration): over time, track hit-rate per confidence bucket

Multi-sensor fields recorded per event:
  combined_confidence   — fusion of TEC + DART + space weather (0-1)
  dart_score_prediction — DART score at detection time (0-1)
  dart_status_prediction— pending / no_buoys / negative / confirmed
  dart_reconciled       — scoring-time DART vs prediction-time DART
  space_weather_score   — ionospheric contamination at detection time

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

try:
    import dart_checker
    DART_AVAILABLE = True
except ImportError:
    DART_AVAILABLE = False

EVENT_QUEUE_FILE = "event_queue.json"
RUNNING_LOG_FILE = "running_log.json"
LOG_FILE         = "scorer.log"

NOAA_API = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

# Confidence threshold for layer-2 detection classification
# TEC-only clean conditions → ~0.55, so 0.35 catches all real detections
# while filtering contaminated or DART-only signals
CONFIDENCE_THRESHOLD = 0.35

# ── Tide gauge network ─────────────────────────────────────────────
GAUGE_NETWORK = {
    "hilo":     {"id": "1617760", "lat":  19.730, "lon": -155.087, "primary": True},
    "midway":   {"id": "1619910", "lat":  28.210, "lon": -177.360, "primary": False},
    "johnston": {"id": "1619543", "lat":  16.735, "lon": -169.527, "primary": False},
    "pago":     {"id": "1770000", "lat": -14.280, "lon": -170.690, "primary": False},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ── I/O helpers ────────────────────────────────────────────────────

def load_queue():
    if not Path(EVENT_QUEUE_FILE).exists():
        return None
    return json.loads(Path(EVENT_QUEUE_FILE).read_text())

def save_queue(q):
    Path(EVENT_QUEUE_FILE).write_text(json.dumps(q, indent=2))

def load_log():
    if Path(RUNNING_LOG_FILE).exists():
        return json.loads(Path(RUNNING_LOG_FILE).read_text())
    return {"scored_events": [], "summary": {}}

def save_log(log_data):
    Path(RUNNING_LOG_FILE).write_text(json.dumps(log_data, indent=2))


# ── Tide gauge fetching ────────────────────────────────────────────

def fetch_tide_gauge(quake_utc_str, station_id, window_hours=48):
    """Fetch NOAA tide gauge data for a single station around event time."""
    quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))
    start_dt = quake_dt - timedelta(hours=2)
    end_dt   = quake_dt + timedelta(hours=window_hours)

    params = {
        "product":      "water_level",
        "application":  "gps_tsunami_detector",
        "begin_date":   start_dt.strftime("%Y%m%d"),
        "end_date":     end_dt.strftime("%Y%m%d"),
        "datum":        "MLLW",
        "station":      station_id,
        "time_zone":    "GMT",
        "units":        "metric",
        "interval":     "6",
        "format":       "json",
    }

    try:
        r = requests.get(NOAA_API, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if "data" not in data:
            log.warning(f"  No tide data from station {station_id}: {data.get('error', 'unknown')}")
            return None
        return data["data"]
    except Exception as e:
        log.error(f"  Tide gauge fetch failed (station {station_id}): {e}")
        return None


def fetch_all_gauges(quake_utc_str):
    """Fetch all gauges. Returns {gauge_name: {raw, tsunami}} dict."""
    results = {}
    for name, cfg in GAUGE_NETWORK.items():
        log.info(f"  Checking gauge: {name.upper()} (station {cfg['id']})")
        raw     = fetch_tide_gauge(quake_utc_str, cfg["id"])
        tsunami = parse_tide_tsunami(raw, quake_utc_str) if raw else None
        results[name] = {
            "station_id":    cfg["id"],
            "lat":           cfg["lat"],
            "lon":           cfg["lon"],
            "primary":       cfg["primary"],
            "raw_available": raw is not None,
            "tsunami":       tsunami,
        }
        if tsunami:
            log.info(
                f"    → TSUNAMI SIGNAL: +{tsunami['arrival_h_post_quake']:.1f}h "
                f"amplitude={tsunami['amplitude_m']:.3f}m "
                f"method={tsunami['detection_method']}"
            )
        else:
            log.info(f"    → No signal")
    return results


def parse_tide_tsunami(tide_data, quake_utc_str):
    """
    Detect tsunami onset in tide gauge data.
    Returns dict or None.
    """
    if not tide_data:
        return None

    quake_dt = datetime.fromisoformat(quake_utc_str.replace("Z", "+00:00"))

    times, vals, flags = [], [], []
    for rec in tide_data:
        try:
            t = datetime.strptime(rec["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            v = float(rec["v"])
            times.append(t)
            vals.append(v)
            flags.append(rec.get("f", "0,0,0,0"))
        except Exception:
            continue

    if len(times) < 10:
        return None

    # NOAA flag-based detection (most reliable)
    flagged = [t for t, f in zip(times, flags)
               if "0,0,1,0" in f and 2.0 <= (t - quake_dt).total_seconds() / 3600 <= 20.0]

    if flagged:
        first_arrival = min(flagged)
        arrival_h = (first_arrival - quake_dt).total_seconds() / 3600
        window_vals = [v for t, v in zip(times, vals)
                       if first_arrival <= t <= first_arrival + timedelta(hours=2)]
        amp = (max(window_vals) - min(window_vals)) / 2 if window_vals else 0.0
        return {
            "onset_utc":             first_arrival.isoformat(),
            "arrival_h_post_quake":  round(arrival_h, 2),
            "amplitude_m":           round(amp, 3),
            "detection_method":      "noaa_flag",
        }

    # Variance-based fallback
    pre = [v for t, v in zip(times, vals) if (t - quake_dt).total_seconds() / 3600 < 1.5]
    if pre:
        base_mean = np.mean(pre)
        base_std  = max(np.std(pre), 0.005)
        for t, v in zip(times, vals):
            h = (t - quake_dt).total_seconds() / 3600
            if 2.0 <= h <= 20.0 and abs(v - base_mean) > 3 * base_std:
                window_vals = [vv for tt, vv in zip(times, vals)
                               if t <= tt <= t + timedelta(hours=2)]
                amp = (max(window_vals) - min(window_vals)) / 2 if window_vals else 0.0
                if amp > 0.05:
                    return {
                        "onset_utc":             t.isoformat(),
                        "arrival_h_post_quake":  round(h, 2),
                        "amplitude_m":           round(amp, 3),
                        "detection_method":      "variance_threshold",
                    }
    return None


# ── Scoring ────────────────────────────────────────────────────────

def reconcile_dart(pred_dart_status, scoring_dart_result):
    """
    Compare prediction-time DART status against scoring-time DART result.
    Returns a reconciliation dict for logging.
    """
    if scoring_dart_result is None:
        return {"reconciled": False, "reason": "no_scoring_dart"}

    scoring_confirmed = scoring_dart_result.get("tsunami_detected", False)
    scoring_buoys     = scoring_dart_result.get("buoys_with_data", 0)

    if pred_dart_status == "pending":
        # Prediction was too early; now we have the full picture
        return {
            "reconciled": True,
            "pred_status": pred_dart_status,
            "scoring_confirmed": scoring_confirmed,
            "scoring_buoys_with_data": scoring_buoys,
            "note": "DART was pending at detection time; scoring-time result is ground truth",
        }
    elif pred_dart_status == "confirmed" and scoring_confirmed:
        return {"reconciled": True, "agreement": "both_confirmed",
                "pred_status": pred_dart_status, "scoring_confirmed": scoring_confirmed}
    elif pred_dart_status == "negative" and not scoring_confirmed:
        return {"reconciled": True, "agreement": "both_negative",
                "pred_status": pred_dart_status, "scoring_confirmed": scoring_confirmed}
    elif pred_dart_status in ("confirmed",) and not scoring_confirmed:
        return {"reconciled": True, "agreement": "disagreement_pred_confirmed_scoring_negative",
                "pred_status": pred_dart_status, "scoring_confirmed": scoring_confirmed}
    elif pred_dart_status in ("negative",) and scoring_confirmed:
        return {"reconciled": True, "agreement": "disagreement_pred_negative_scoring_confirmed",
                "pred_status": pred_dart_status, "scoring_confirmed": scoring_confirmed}
    else:
        return {"reconciled": True, "pred_status": pred_dart_status,
                "scoring_confirmed": scoring_confirmed}


def score_event(event, gauge_results, dart_result=None):
    """
    Score a single prediction against multi-gauge truth.

    Layer 1 (binary):    outcome based on TEC detected vs tide gauge signal
    Layer 2 (confidence): confidence_detected using combined_confidence threshold
    Layer 3 (DART):       reconcile prediction-time vs scoring-time DART
    """
    pred              = event.get("prediction", {})
    detected_by_algo  = pred.get("detected", False)
    anchor            = event.get("primary_anchor")

    # ── Multi-sensor fields from prediction ───────────────────────
    combined_confidence   = pred.get("combined_confidence")
    dart_score_pred       = pred.get("dart_score")
    dart_status_pred      = pred.get("dart_status")
    sw_score_pred         = pred.get("space_weather_score")
    sw_gated              = pred.get("space_weather_gated", False)
    sw_flags              = pred.get("space_weather_flags", [])

    # Layer 2: confidence-based detection
    confidence_detected = (
        combined_confidence is not None
        and combined_confidence >= CONFIDENCE_THRESHOLD
    )

    # ── Gauge truth ───────────────────────────────────────────────
    hilo             = gauge_results.get("hilo", {})
    tide_tsunami     = hilo.get("tsunami")
    secondary_signals = {
        name: g["tsunami"]
        for name, g in gauge_results.items()
        if not g["primary"] and g["tsunami"] is not None
    }
    any_gauge_tsunami = tide_tsunami is not None or len(secondary_signals) > 0
    corroborated      = len(secondary_signals) > 0

    # ── DART reconciliation ───────────────────────────────────────
    dart_reconcile = reconcile_dart(dart_status_pred, dart_result)

    # ── Build score record ────────────────────────────────────────
    score = {
        # Identity
        "usgs_id":               event["usgs_id"],
        "quake_utc":             event["quake_utc"],
        "magnitude":             event["magnitude"],
        "place":                 event["place"],
        "anchor":                anchor,

        # Legacy fields (keep for dashboard backward compat)
        "kp":                    pred.get("kp"),
        "algo_detected":         detected_by_algo,
        "gauge_tsunami":         tide_tsunami is not None,
        "any_gauge_tsunami":     any_gauge_tsunami,
        "corroborated_by":       list(secondary_signals.keys()),

        # Multi-sensor confidence (new)
        "combined_confidence":        combined_confidence,
        "confidence_detected":        confidence_detected,
        "confidence_threshold":       CONFIDENCE_THRESHOLD,
        "dart_score_prediction":      dart_score_pred,
        "dart_status_prediction":     dart_status_pred,
        "space_weather_score":        sw_score_pred,
        "space_weather_gated":        sw_gated,
        "space_weather_flags":        sw_flags,
        "dart_reconciliation":        dart_reconcile,

        # Scoring-time DART (existing fields, kept for compat)
        "dart_detected":         dart_result["tsunami_detected"] if dart_result else None,
        "dart_confirming_buoys": dart_result["confirming_buoys"] if dart_result else None,
        "dart_buoys_checked":    dart_result["buoys_checked"] if dart_result else None,
        "dart_network":          dart_result if dart_result else None,

        # Gauge network detail
        "gauge_network": {
            name: {
                "signal":      bool(g["tsunami"]),
                "arrival_h":   g["tsunami"]["arrival_h_post_quake"] if g["tsunami"] else None,
                "amplitude_m": g["tsunami"]["amplitude_m"] if g["tsunami"] else None,
                "method":      g["tsunami"]["detection_method"] if g["tsunami"] else None,
            }
            for name, g in gauge_results.items()
        },

        # Outcomes (filled below)
        "outcome":                   None,
        "outcome_confidence":         None,  # layer-2 outcome
        "lead_time_min":              None,
        "amplitude_predicted_m":      None,
        "amplitude_actual_m":         None,
        "amplitude_error_pct":        None,
        "timing_error_min":           None,
        "notes":                      [],
    }

    # ── Layer 1 outcome (binary TEC) ──────────────────────────────
    if detected_by_algo and tide_tsunami:
        score["outcome"] = "TRUE_POSITIVE"
    elif not detected_by_algo and not tide_tsunami:
        score["outcome"] = ("CORRECT_ABSTENTION_NO_ANCHOR" if not anchor
                            else "TRUE_NEGATIVE")
    elif detected_by_algo and not tide_tsunami:
        if corroborated:
            score["outcome"] = "TRUE_POSITIVE"
            score["notes"].append(
                f"Hilo no signal; confirmed by: {list(secondary_signals.keys())}"
            )
            tide_tsunami = list(secondary_signals.values())[0]
        else:
            score["outcome"] = "FALSE_POSITIVE"
    elif not detected_by_algo and tide_tsunami:
        score["outcome"] = ("GEOMETRY_LIMITED_MISS" if not anchor
                            else "FALSE_NEGATIVE")
        if corroborated:
            score["notes"].append(
                f"Multi-gauge confirmed: {list(secondary_signals.keys())}"
            )

    # ── Layer 2 outcome (confidence-based) ────────────────────────
    if combined_confidence is not None:
        if confidence_detected and any_gauge_tsunami:
            score["outcome_confidence"] = "TRUE_POSITIVE"
        elif not confidence_detected and not any_gauge_tsunami:
            score["outcome_confidence"] = "TRUE_NEGATIVE"
        elif confidence_detected and not any_gauge_tsunami:
            score["outcome_confidence"] = "FALSE_POSITIVE"
        else:
            score["outcome_confidence"] = "FALSE_NEGATIVE"

        # Log disagreements between layers
        if score["outcome_confidence"] != score["outcome"]:
            if score["outcome"] in ("TRUE_POSITIVE", "FALSE_POSITIVE"):
                score["notes"].append(
                    f"Layer disagreement: binary={score['outcome']} "
                    f"confidence={score['outcome_confidence']} "
                    f"(conf={combined_confidence:.3f} threshold={CONFIDENCE_THRESHOLD})"
                )

    # ── Space weather gate note ───────────────────────────────────
    if sw_gated:
        score["notes"].append(
            f"Space weather gated at detection time "
            f"(score={sw_score_pred:.2f}, flags={'; '.join(sw_flags)})"
        )

    # ── Quantitative metrics (true positives only) ────────────────
    if tide_tsunami and detected_by_algo:
        det = pred.get("detection") or {}
        wf  = pred.get("wave_forecast") or {}

        algo_onset_h     = det.get("post_h", 0)
        actual_arrival_h = tide_tsunami["arrival_h_post_quake"]
        score["lead_time_min"] = round((actual_arrival_h - algo_onset_h) * 60)

        if wf.get("predicted_wave_m") is not None:
            pred_wave   = wf["predicted_wave_m"]
            actual_wave = tide_tsunami["amplitude_m"]
            score["amplitude_predicted_m"] = pred_wave
            score["amplitude_actual_m"]    = actual_wave
            if actual_wave > 0:
                score["amplitude_error_pct"] = round(
                    (pred_wave - actual_wave) / actual_wave * 100, 1
                )

    if tide_tsunami:
        score["tide_gauge_truth"] = tide_tsunami

    return score


# ── Summary ────────────────────────────────────────────────────────

def update_summary(log_data):
    """Recompute running summary statistics including confidence calibration."""
    events = log_data["scored_events"]
    if not events:
        return

    # Layer 1 (binary) stats
    outcomes = [e.get("outcome") for e in events if e.get("outcome")]
    tp = outcomes.count("TRUE_POSITIVE")
    tn = (outcomes.count("TRUE_NEGATIVE") +
          outcomes.count("CORRECT_ABSTENTION_NO_ANCHOR"))
    fp = outcomes.count("FALSE_POSITIVE")
    fn = (outcomes.count("FALSE_NEGATIVE") +
          outcomes.count("GEOMETRY_LIMITED_MISS"))

    # Layer 2 (confidence) stats
    conf_outcomes = [e.get("outcome_confidence") for e in events
                     if e.get("outcome_confidence")]
    c_tp = conf_outcomes.count("TRUE_POSITIVE")
    c_tn = conf_outcomes.count("TRUE_NEGATIVE")
    c_fp = conf_outcomes.count("FALSE_POSITIVE")
    c_fn = conf_outcomes.count("FALSE_NEGATIVE")

    # Quantitative metrics
    lead_times = [e["lead_time_min"] for e in events
                  if e.get("lead_time_min") is not None]
    amp_errors = [abs(e["amplitude_error_pct"]) for e in events
                  if e.get("amplitude_error_pct") is not None]
    confidences = [e["combined_confidence"] for e in events
                   if e.get("combined_confidence") is not None]

    # Confidence calibration buckets
    # For each bucket: what fraction of predictions were actually tsunamis?
    buckets = {
        "0.0-0.2": [], "0.2-0.4": [], "0.4-0.6": [],
        "0.6-0.8": [], "0.8-1.0": [],
    }
    bucket_ranges = [
        (0.0, 0.2, "0.0-0.2"), (0.2, 0.4, "0.2-0.4"),
        (0.4, 0.6, "0.4-0.6"), (0.6, 0.8, "0.6-0.8"),
        (0.8, 1.0, "0.8-1.0"),
    ]
    for e in events:
        conf   = e.get("combined_confidence")
        actual = e.get("any_gauge_tsunami", False)
        if conf is not None:
            for lo, hi, name in bucket_ranges:
                if lo <= conf <= hi:
                    buckets[name].append(actual)
                    break

    calibration = {}
    for name, vals in buckets.items():
        if vals:
            calibration[name] = {
                "n":        len(vals),
                "hit_rate": round(sum(vals) / len(vals), 3),
            }

    # DART integration stats
    dart_confirmed_events = [e for e in events
                             if e.get("dart_detected") is True]
    dart_pending_events   = [e for e in events
                             if e.get("dart_status_prediction") == "pending"]

    log_data["summary"] = {
        # Layer 1
        "total_scored":             len(events),
        "true_positives":           tp,
        "true_negatives":           tn,
        "false_positives":          fp,
        "false_negatives":          fn,
        "tpr":   round(tp / (tp + fn), 3) if (tp + fn) > 0 else None,
        "fpr":   round(fp / (fp + tn), 3) if (fp + tn) > 0 else None,

        # Layer 2 (confidence-based)
        "confidence_tp":  c_tp,
        "confidence_tn":  c_tn,
        "confidence_fp":  c_fp,
        "confidence_fn":  c_fn,
        "confidence_tpr": round(c_tp / (c_tp + c_fn), 3) if (c_tp + c_fn) > 0 else None,
        "confidence_fpr": round(c_fp / (c_fp + c_tn), 3) if (c_fp + c_tn) > 0 else None,
        "confidence_threshold": CONFIDENCE_THRESHOLD,

        # Quantitative
        "mean_lead_time_min":       round(np.mean(lead_times), 1) if lead_times else None,
        "median_lead_time_min":     round(np.median(lead_times), 1) if lead_times else None,
        "mean_amplitude_error_pct": round(np.mean(amp_errors), 1) if amp_errors else None,
        "mean_confidence":          round(np.mean(confidences), 3) if confidences else None,

        # DART
        "dart_confirmed_events":    len(dart_confirmed_events),
        "dart_pending_at_detection": len(dart_pending_events),

        # Calibration
        "confidence_calibration":   calibration,

        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


# ── Main ────────────────────────────────────────────────────────────

def is_ready_to_score(event):
    if event.get("scored"):
        return False
    if event.get("status") != "predicted":
        return False
    quake_time = datetime.fromisoformat(event["quake_utc"].replace("Z", "+00:00"))
    hours_since = (datetime.now(timezone.utc) - quake_time).total_seconds() / 3600
    return hours_since >= 24.0


def main(event_id=None, force=False):
    log.info("=" * 55)
    log.info("GPS Tsunami Detector — Scorer v2 (multi-sensor)")
    log.info("=" * 55)

    queue = load_queue()
    if not queue:
        return

    log_data      = load_log()
    already_scored = {e["usgs_id"] for e in log_data["scored_events"]}

    events = queue["events"]
    if event_id:
        events = [e for e in events if e["usgs_id"] == event_id]

    ready = [e for e in events
             if (is_ready_to_score(e) or force)
             and e["usgs_id"] not in already_scored]

    log.info(f"Events ready to score: {len(ready)}")

    for event in ready:
        log.info(f"\nScoring: {event['usgs_id']}  {event['place']}  Mw{event['magnitude']}")

        pred = event.get("prediction", {})
        if pred.get("combined_confidence") is not None:
            log.info(
                f"  Prediction: TEC={'yes' if pred.get('detected') else 'no'}  "
                f"DART={pred.get('dart_status','n/a')}({pred.get('dart_score', 0):.2f})  "
                f"SW={pred.get('space_weather_score', 0):.2f}  "
                f"combined={pred['combined_confidence']:.3f}"
            )

        # Fetch all gauges
        gauge_results = fetch_all_gauges(event["quake_utc"])
        any_signal    = any(g["tsunami"] for g in gauge_results.values())

        if any_signal:
            confirmed = [n for n, g in gauge_results.items() if g["tsunami"]]
            log.info(f"  Tsunami signal confirmed at: {confirmed}")
        else:
            log.info(f"  No tsunami signal at any gauge")

        # Scoring-time DART check (24h post-event = full wave passage window)
        dart_result = None
        if DART_AVAILABLE and event.get("lat") and event.get("lon"):
            log.info(f"  Checking DART buoy network (scoring time)...")
            dart_result = dart_checker.check_dart_network(
                event["quake_utc"], event["lat"], event["lon"]
            )
        else:
            log.info("  DART check skipped (no coordinates or module unavailable)")

        # Score
        score = score_event(event, gauge_results, dart_result)

        # Log outcome
        log.info(f"  Outcome (binary):     {score['outcome']}")
        if score.get("outcome_confidence"):
            log.info(f"  Outcome (confidence): {score['outcome_confidence']} "
                     f"(conf={score['combined_confidence']:.3f})")
        if score.get("dart_reconciliation", {}).get("agreement"):
            log.info(f"  DART reconciled:      {score['dart_reconciliation']['agreement']}")
        for note in score.get("notes", []):
            log.info(f"  Note: {note}")
        if score.get("lead_time_min") is not None:
            log.info(f"  Lead time: {score['lead_time_min']} min")
        if score.get("amplitude_error_pct") is not None:
            log.info(f"  Amplitude error: {score['amplitude_error_pct']:+.0f}%")

        # Update queue and log
        event["scored"]      = True
        event["score"]       = score
        event["status"]      = "scored"
        event["scored_utc"]  = datetime.now(timezone.utc).isoformat()

        log_data["scored_events"].append(score)
        update_summary(log_data)
        save_queue(queue)
        save_log(log_data)
        log.info(f"  Updated: {RUNNING_LOG_FILE}")

    # Running summary
    if log_data["scored_events"]:
        s = log_data["summary"]
        log.info(f"\n{'='*55}")
        log.info(f"RUNNING SUMMARY  ({s['total_scored']} events scored)")
        log.info(f"  Binary:     TP={s['true_positives']} TN={s['true_negatives']} "
                 f"FP={s['false_positives']} FN={s['false_negatives']}")
        if s.get("confidence_tpr") is not None:
            log.info(f"  Confidence: TP={s['confidence_tp']} TN={s['confidence_tn']} "
                     f"FP={s['confidence_fp']} FN={s['confidence_fn']}")
        if s.get("tpr") is not None:
            log.info(f"  TPR={s['tpr']:.3f}  FPR={s['fpr']:.3f}")
        if s.get("mean_lead_time_min") is not None:
            log.info(f"  Lead time: mean={s['mean_lead_time_min']}min  "
                     f"median={s['median_lead_time_min']}min")
        if s.get("mean_amplitude_error_pct") is not None:
            log.info(f"  Amplitude error: {s['mean_amplitude_error_pct']:.1f}% mean absolute")
        if s.get("mean_confidence") is not None:
            log.info(f"  Mean confidence: {s['mean_confidence']:.3f}")
        if s.get("confidence_calibration"):
            log.info("  Calibration (confidence → hit rate):")
            for bucket, data in s["confidence_calibration"].items():
                log.info(f"    {bucket}: {data['hit_rate']:.0%} ({data['n']} events)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", help="Score specific USGS event ID")
    parser.add_argument("--force", action="store_true",
                        help="Score even if <24h elapsed")
    args = parser.parse_args()
    main(event_id=args.event, force=args.force)
