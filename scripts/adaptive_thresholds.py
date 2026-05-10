import json, os, math
from datetime import datetime, timezone
from pathlib import Path

# Frozen parameters (from detector_runner.py)
FROZEN = {
    "SNR_THRESHOLD":    2.0,
    "SPEED_MIN":        150.0,
    "SPEED_MAX":        350.0,
    "MIN_POST_QUAKE_H": 1.5,
    "MAX_POST_QUAKE_H": 22.0,
    "MIN_ARC_EPOCHS":   120,
    "MIN_DURATION_MIN": 3.0,
    "LONG_BASELINE_KM": 1000.0,
}

# Priors (Normal-Normal conjugate): (mu_0, sigma_0, n_0)
# Speed: AGW literature 150-350 m/s, center 250, std 60
# SNR:   minimum detectable ~2.0, prior mu=3.0, std=1.0
PRIORS = {
    "speed_ms": (250.0, 60.0, 2),
    "snr_near": (3.0,   1.0,  2),
    "post_h":   (6.0,   4.0,  2),
}

RESULTS_FILE = "backtest_results.json"
RUNNING_LOG  = "running_log.json"
OUT_FILE     = "threshold_recommendations.json"


def load_json(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def normal_normal_posterior(obs, mu_0, sigma_0, n_0):
    n = len(obs)
    if n == 0:
        return mu_0, sigma_0, n_0
    obs_mean = sum(obs) / n
    prec_0 = n_0 / (sigma_0 ** 2)
    prec_n = n   / (sigma_0 ** 2)
    prec_post = prec_0 + prec_n
    mu_post = (prec_0 * mu_0 + prec_n * obs_mean) / prec_post
    sigma_post = math.sqrt(1.0 / prec_post)
    return round(mu_post, 2), round(sigma_post, 2), n_0 + n


def extract_tp_observations(results_data):
    speeds, snrs, post_hs = [], [], []
    if not results_data:
        return speeds, snrs, post_hs
    for r in results_data.get("results", []):
        if r.get("bt_outcome") != "TRUE_POSITIVE":
            continue
        det = (r.get("prediction") or {}).get("detection")
        if not det:
            continue
        if "speed_ms" in det:
            speeds.append(float(det["speed_ms"]))
        if "snr_near" in det:
            snrs.append(float(det["snr_near"]))
        if "post_h" in det:
            post_hs.append(float(det["post_h"]))
    return speeds, snrs, post_hs


def extract_live_observations(running_log):
    speeds, snrs, post_hs = [], [], []
    if not running_log:
        return speeds, snrs, post_hs
    for ev in running_log.get("events", []):
        if ev.get("result") != "TRUE_POSITIVE":
            continue
        det = (ev.get("prediction") or {}).get("detection")
        if not det:
            continue
        if "speed_ms" in det:
            speeds.append(float(det["speed_ms"]))
        if "snr_near" in det:
            snrs.append(float(det["snr_near"]))
        if "post_h" in det:
            post_hs.append(float(det["post_h"]))
    return speeds, snrs, post_hs


def compute_recommendations(speeds, snrs, post_hs):
    recs = {}

    mu_s, sig_s, n_s = normal_normal_posterior(speeds, *PRIORS["speed_ms"])
    recs["SPEED_MIN"] = {
        "frozen":         FROZEN["SPEED_MIN"],
        "recommended":    round(max(100.0, mu_s - 2 * sig_s), 1),
        "posterior_mean": mu_s,
        "posterior_std":  sig_s,
        "n_obs":          n_s,
        "basis":          "posterior_mean - 2sigma",
    }
    recs["SPEED_MAX"] = {
        "frozen":         FROZEN["SPEED_MAX"],
        "recommended":    round(min(500.0, mu_s + 2 * sig_s), 1),
        "posterior_mean": mu_s,
        "posterior_std":  sig_s,
        "n_obs":          n_s,
        "basis":          "posterior_mean + 2sigma",
    }

    mu_r, sig_r, n_r = normal_normal_posterior(snrs, *PRIORS["snr_near"])
    recs["SNR_THRESHOLD"] = {
        "frozen":         FROZEN["SNR_THRESHOLD"],
        "recommended":    round(max(1.5, mu_r - 0.5 * sig_r), 2),
        "posterior_mean": mu_r,
        "posterior_std":  sig_r,
        "n_obs":          n_r,
        "basis":          "posterior_mean - 0.5sigma (conservative)",
    }

    mu_p, sig_p, n_p = normal_normal_posterior(post_hs, *PRIORS["post_h"])
    recs["MAX_POST_QUAKE_H"] = {
        "frozen":         FROZEN["MAX_POST_QUAKE_H"],
        "recommended":    round(min(24.0, mu_p + 2 * sig_p), 1),
        "posterior_mean": mu_p,
        "posterior_std":  sig_p,
        "n_obs":          n_p,
        "basis":          "posterior_mean + 2sigma (capture late arrivals)",
    }

    return recs


def print_report(recs, speeds, snrs, post_hs):
    print()
    print("=" * 60)
    print("GPS TSUNAMI -- ADAPTIVE THRESHOLD RECOMMENDATIONS")
    print(f"Run: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M UTC')}")
    print(f"Observations: {len(speeds)} TP detections")
    print("=" * 60)
    print(f"  Speeds (m/s):  {[round(s,1) for s in speeds]}")
    print(f"  SNRs:          {[round(s,2) for s in snrs]}")
    print(f"  Post-quake h:  {[round(p,1) for p in post_hs]}")
    print()
    any_change = False
    for param, r in recs.items():
        delta = r["recommended"] - r["frozen"]
        flag = "  (no change)" if abs(delta) < 0.01 else f"  <-- DELTA {delta:+.2f}"
        if abs(delta) >= 0.01:
            any_change = True
        print(f"  {param}")
        print(f"    Frozen:      {r['frozen']}")
        print(f"    Recommended: {r['recommended']}{flag}")
        print(f"    Posterior:   mean={r['posterior_mean']}  std={r['posterior_std']}  n={r['n_obs']}")
        print(f"    Basis:       {r['basis']}")
        print()
    if not any_change:
        print("  All parameters within tolerance of frozen values.")
        print("  No updates recommended at this sample size.")
    print("NOTE: Recommendations are advisory only.")
    print("      Apply manually by editing detector_runner.py constants.")
    print("      Re-freeze PARAM_FREEZE_DATE after any update.")
    print("=" * 60)


def main():
    print("Loading backtest results...")
    bt = load_json(RESULTS_FILE)
    print("Loading running log...")
    rl = load_json(RUNNING_LOG)

    bt_speeds, bt_snrs, bt_post = extract_tp_observations(bt)
    lv_speeds, lv_snrs, lv_post = extract_live_observations(rl)

    speeds  = bt_speeds  + lv_speeds
    snrs    = bt_snrs    + lv_snrs
    post_hs = bt_post    + lv_post

    print(f"Total TP observations: {len(speeds)} ({len(bt_speeds)} backtest + {len(lv_speeds)} live)")

    recs = compute_recommendations(speeds, snrs, post_hs)
    print_report(recs, speeds, snrs, post_hs)

    out = {
        "run_utc":         datetime.now(timezone.utc).isoformat(),
        "n_tp_backtest":   len(bt_speeds),
        "n_tp_live":       len(lv_speeds),
        "n_tp_total":      len(speeds),
        "frozen":          FROZEN,
        "recommendations": recs,
        "observations": {
            "speeds":  speeds,
            "snrs":    snrs,
            "post_hs": post_hs,
        },
    }
    Path(OUT_FILE).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nWrote: {OUT_FILE}")


if __name__ == "__main__":
    main()
