#!/usr/bin/env python3
"""
Retrospective Van Allen Probes (RBSP) context for backtest earthquake events.

Uses the same event list as backtest.py (BUILTIN_EVENTS_CSV) and NASA CDAWeb HAPI
(no extra Python deps beyond stdlib + numpy/pandas already in requirements.txt).

Data pulled:
  - OMNI2 hourly: KP1800, DST1800 (solar wind / ring-current context).
  - RBSP-A HOPE L3: Ion_density with L, MLT (plasmasphere / inner magnetosphere proxy).

RBSP-A commissioning science window is approx 2012-09 onward through mission end ~2019;
events outside that window are skipped for in-situ RBSP metrics but still get OMNI
when the quake date is within OMNI coverage.

Example:
  python3 scripts/van_allen_backtest.py --hours-before 72 --hours-after 72
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Reuse canonical backtest event table
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backtest import BUILTIN_EVENTS_CSV  # noqa: E402

HAPI_BASE = "https://cdaweb.gsfc.nasa.gov/hapi"
OMNI_ID = "OMNI2_H0_MRG1HR"
HOPE_ID = "RBSPA_REL04_ECT-HOPE-MOM-L3@0"
FILL = -1.0e31
RBSP_A_START = datetime(2012, 9, 1, tzinfo=timezone.utc)
RBSP_A_END = datetime(2019, 10, 18, tzinfo=timezone.utc)
L_MIN, L_MAX = 2.0, 8.0


def load_env(path: Path) -> None:
    import os

    try:
        raw = path.read_bytes().lstrip(b"\xef\xbb\xbf").decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except OSError:
        pass


def _http_get(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-detection/van_allen_backtest"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def hapi_csv(dataset_id: str, parameters: list[str], t0: datetime, t1: datetime) -> pd.DataFrame:
    """Fetch HAPI CSV; parameters must follow server catalog order after Time."""
    params = ",".join(["Time"] + parameters)
    q = urllib.parse.urlencode(
        {
            "id": dataset_id,
            "parameters": params,
            "time.min": t0.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "time.max": t1.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "format": "csv",
        }
    )
    url = f"{HAPI_BASE}/data?{q}"
    text = _http_get(url)
    if text.lstrip().startswith("{"):
        obj = json.loads(text)
        st = obj.get("status", {})
        if st.get("code") == 1201:
            return pd.DataFrame()
        raise RuntimeError(f"HAPI error: {st}")
    buf = io.StringIO(text)
    df = pd.read_csv(buf, names=["time"] + parameters, parse_dates=["time"], na_values=[str(FILL), "-1.0E31"])
    return df


def parse_quake_utc(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _finite_series(s: pd.Series) -> np.ndarray:
    x = s.to_numpy(dtype=float)
    return x[np.isfinite(x)]


def stats_hope(df: pd.DataFrame, t_start: datetime, t_end: datetime) -> tuple[int, float | None]:
    if df.empty:
        return 0, None
    m = (df["time"] >= pd.Timestamp(t_start)) & (df["time"] <= pd.Timestamp(t_end))
    m &= df["L"].between(L_MIN, L_MAX)
    sub = df.loc[m, "Ion_density"]
    x = _finite_series(sub)
    x = x[x > 0]
    if x.size < 3:
        return int(sub.notna().sum()), None
    return int(x.size), float(np.median(np.log10(x)))


def stats_omni(df: pd.DataFrame, t_start: datetime, t_end: datetime) -> tuple[float | None, float | None]:
    """Return (mean Kp on 0--9 scale, mean Dst nT). KP1800 in OMNI is Kp*10; fill=99."""
    if df.empty:
        return None, None
    m = (df["time"] >= pd.Timestamp(t_start)) & (df["time"] <= pd.Timestamp(t_end))
    kp = _finite_series(df.loc[m, "KP1800"])
    kp = kp[(kp >= 0) & (kp <= 90) & (kp != 99)]
    dst = _finite_series(df.loc[m, "DST1800"])
    kp_mean = float(np.mean(kp) / 10.0) if kp.size else None
    dst_mean = float(np.mean(dst)) if dst.size else None
    return kp_mean, dst_mean


def run_one_event(
    row: dict[str, str],
    hours_before: int,
    hours_after: int,
    sleep_s: float,
) -> dict[str, Any]:
    usgs_id = row["usgs_id"]
    t0 = parse_quake_utc(row["quake_utc"])
    win_pre0 = t0 - timedelta(hours=hours_before)
    win_post1 = t0 + timedelta(hours=hours_after)

    out: dict[str, Any] = {
        "usgs_id": usgs_id,
        "quake_utc": t0.isoformat().replace("+00:00", "Z"),
        "mw": float(row["mw"]),
        "known_outcome": row.get("known_outcome", ""),
        "notes": row.get("notes", ""),
        "window_hours": {"before": hours_before, "after": hours_after},
        "rbsp_in_situ": RBSP_A_START <= t0 <= RBSP_A_END,
    }

    if not out["rbsp_in_situ"]:
        out["skip_reason"] = "quake_time outside RBSP-A primary science era (use OMNI only below)"
    else:
        out["skip_reason"] = None

    # OMNI: extend a little for hourly alignment
    try:
        omni = hapi_csv(OMNI_ID, ["KP1800", "DST1800"], win_pre0 - timedelta(hours=2), win_post1 + timedelta(hours=2))
        time.sleep(sleep_s)
    except Exception as e:
        omni = pd.DataFrame()
        out["omni_error"] = str(e)

    pre0 = t0 - timedelta(hours=hours_before)
    pre1 = t0 - timedelta(hours=hours_before // 3)  # early baseline
    mid0 = t0 - timedelta(hours=24)
    near0 = t0 - timedelta(hours=6)

    segments = {
        "baseline_early": (pre0, pre1),
        "pre_24h": (t0 - timedelta(hours=24), t0),
        "pre_6h": (near0, t0),
        "post_0_24h": (t0, t0 + timedelta(hours=24)),
        "post_24_48h": (t0 + timedelta(hours=24), t0 + timedelta(hours=48)),
        "full_window": (win_pre0, win_post1),
    }

    omni_seg: dict[str, Any] = {}
    for name, (a, b) in segments.items():
        kp_m, dst_m = stats_omni(omni, a, b)
        omni_seg[name] = {"mean_kp": kp_m, "mean_dst_nT": dst_m}
    out["omni_segments"] = omni_seg

    if not out["rbsp_in_situ"]:
        out["hope"] = {"status": "skipped", "reason": out["skip_reason"]}
        return out

    try:
        hope = hapi_csv(HOPE_ID, ["Ion_density", "L", "MLT"], win_pre0, win_post1)
        time.sleep(sleep_s)
    except Exception as e:
        out["hope"] = {"status": "error", "error": str(e)}
        return out

    hope_seg: dict[str, Any] = {}
    for name, (a, b) in segments.items():
        n, med = stats_hope(hope, a, b)
        hope_seg[name] = {"n_samples_L2_8": n, "median_log10_ion_density": med}
    out["hope_segments"] = hope_seg

    # Simple "marker" heuristic: change from baseline to pre-quake vs post-quake
    b_med = hope_seg.get("baseline_early", {}).get("median_log10_ion_density")
    p24 = hope_seg.get("pre_24h", {}).get("median_log10_ion_density")
    post = hope_seg.get("post_0_24h", {}).get("median_log10_ion_density")
    marker = {
        "delta_pre24_minus_baseline_log10": None
        if (b_med is None or p24 is None)
        else round(p24 - b_med, 4),
        "delta_post0_24_minus_pre24_log10": None
        if (p24 is None or post is None)
        else round(post - p24, 4),
    }
    out["hope_markers_log10_density"] = marker
    out["hope"] = {"status": "ok", "n_rows": int(len(hope))}
    return out


def main() -> None:
    load_env(_REPO_ROOT / ".env")
    p = argparse.ArgumentParser(description="Van Allen / RBSP context for backtest events (CDAWeb HAPI).")
    p.add_argument("--hours-before", type=int, default=72)
    p.add_argument("--hours-after", type=int, default=72)
    p.add_argument("--sleep", type=float, default=0.35, help="Delay between HAPI calls (seconds).")
    p.add_argument("--csv", type=str, default=None, help="Optional CSV path; default is backtest.py builtin list.")
    p.add_argument("--event", type=str, default=None, help="Single usgs_id to process.")
    args = p.parse_args()

    csv_str = Path(args.csv).read_text(encoding="utf-8") if args.csv else BUILTIN_EVENTS_CSV
    rows = list(csv.DictReader(io.StringIO(csv_str.strip())))
    if args.event:
        rows = [r for r in rows if r["usgs_id"] == args.event]
        if not rows:
            print(f"Unknown event id: {args.event}", file=sys.stderr)
            sys.exit(1)

    results = []
    for row in rows:
        print(f"Fetching: {row['usgs_id']} {row['quake_utc']}", flush=True)
        results.append(run_one_event(row, args.hours_before, args.hours_after, args.sleep))

    out_path = _REPO_ROOT / "van_allen_backtest_results.json"
    summary_path = _REPO_ROOT / "van_allen_backtest_summary.txt"
    out_path.write_text(json.dumps({"generated_utc": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2), encoding="utf-8")

    lines = [
        "Van Allen / RBSP-A HOPE + OMNI2 retrospective (CDAWeb HAPI)",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"L-shell filter for HOPE stats: [{L_MIN}, {L_MAX}]",
        "",
        "Interpretation:",
        "- Ion_density (HOPE) is a plasmasphere / thermal plasma proxy, not earthquake precursors.",
        "- Kp / Dst summarize global geomagnetic activity; large |Dst| or Kp usually dominates",
        "  any magnetospheric 'signal' around arbitrary timestamps.",
        "",
        "Per event:",
        "=" * 72,
    ]
    for r in results:
        lines.append(f"{r['usgs_id']}  Mw{r['mw']}  {r['quake_utc'][:10]}  {r.get('known_outcome','')}")
        lines.append(f"  {r.get('notes','')[:68]}")
        om = r.get("omni_segments", {})
        fw = om.get("full_window", {})
        lines.append(f"  OMNI full-window mean Kp={fw.get('mean_kp')}  mean Dst={fw.get('mean_dst_nT')} nT")
        if r.get("hope_segments"):
            hs = r["hope_segments"]
            lines.append(
                f"  HOPE median log10(n) pre_24h={hs.get('pre_24h',{}).get('median_log10_ion_density')} "
                f"post_0_24h={hs.get('post_0_24h',{}).get('median_log10_ion_density')}"
            )
            mk = r.get("hope_markers_log10_density", {})
            lines.append(
                f"  Markers (log10 n): d(pre24-baseline)={mk.get('delta_pre24_minus_baseline_log10')} "
                f"d(post-pre24)={mk.get('delta_post0_24_minus_pre24_log10')}"
            )
        else:
            lines.append(f"  HOPE: {r.get('hope', {}).get('status','?')}  {r.get('skip_reason','')}")
        lines.append("")

    summary_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
