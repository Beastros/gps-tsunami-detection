"""
Updated Calibration Regime-Split
==================================
Far-field calibration using all confirmed detections with
measured wave heights at Hilo tide gauge.

Confirmed detection events with calibration data:
  Tōhoku 2011    Mw 9.0  wave=1.318m  dist=6200km   station=KOKB
  Haida Gwaii 12 Mw 7.7  wave=0.653m  dist=4480km   station=MKEA
  Chile 2010     Mw 8.8  wave=0.464m  dist=10617km  station=MKEA (cascading)
  Kuril 2006     Mw 8.3  wave=0.418m  dist=5900km   station=MKEA

Non-detections characterizing detection limits:
  Kuril 2007     Mw 8.1  wave=0.105m  → Below amplitude threshold
  Peru 2001      Mw 8.4  wave=0.282m  → No upstream anchor + daytime masking
  Sumatra 2004   Mw 9.1  wave=~0.4m   → Hawaii >11,000km detection range limit
  Samoa 2009     Mw 8.1  wave=~0.2m   → No upstream anchor (PAGO unavailable)

Run: python calibration_updated.py
"""

import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.stats import pearsonr

# ── Calibration dataset ───────────────────────────────────────────
# All confirmed detections with TEC amplitude from coherence pipeline
# and tide gauge wave height at Hilo

CALIB = [
    # name, Mw, TEC_TECU, dist_km (station to epicenter), wave_m (Hilo)
    {"name":"Tōhoku 2011",     "mw":9.0, "tec":0.5382, "dist":6200,  "wave":1.318, "corridor":"GUAM→Hawaii"},
    {"name":"Haida Gwaii 2012","mw":7.7, "tec":1.0278, "dist":4480,  "wave":0.653, "corridor":"BC→Hawaii"},
    {"name":"Chile 2010",      "mw":8.8, "tec":1.1531, "dist":10617, "wave":0.464, "corridor":"SA→Hawaii"},
    {"name":"Kuril 2006",      "mw":8.3, "tec":0.4976, "dist":5900,  "wave":0.418, "corridor":"GUAM→Hawaii"},
]

# ── Detection limits ──────────────────────────────────────────────
LIMITS = [
    {"name":"Kuril 2007",  "mw":8.1, "wave":0.105, "reason":"Below TEC threshold (~0.1m)"},
    {"name":"Peru 2001",   "mw":8.4, "wave":0.282, "reason":"No anchor + daytime masking"},
    {"name":"Sumatra 2004","mw":9.1, "wave":0.40,  "reason":"Range limit >11,000km"},
    {"name":"Samoa 2009",  "mw":8.1, "wave":0.20,  "reason":"No upstream anchor"},
]

# ── Frozen calibration model ──────────────────────────────────────
CALIB_A = 2283.839
CALIB_B = 0.771
CALIB_C = 2.614

def model(X, A, B, C):
    tec, mw, dist = X
    return A * tec * (10**(B*mw)) / (dist**C)

# ── Fit updated model ─────────────────────────────────────────────
tec  = np.array([c['tec']  for c in CALIB])
mw   = np.array([c['mw']   for c in CALIB])
dist = np.array([c['dist'] for c in CALIB])
wave = np.array([c['wave'] for c in CALIB])

# Try fitting with new data
try:
    popt, pcov = curve_fit(
        lambda X,A,B,C: model(X,A,B,C),
        (tec, mw, dist), wave,
        p0=[CALIB_A, CALIB_B, CALIB_C],
        bounds=([0,0,0],[1e6,3,6]),
        maxfev=10000
    )
    A_fit, B_fit, C_fit = popt
    wave_pred_new = model((tec,mw,dist), A_fit, B_fit, C_fit)
    ss_res = np.sum((wave - wave_pred_new)**2)
    ss_tot = np.sum((wave - np.mean(wave))**2)
    r2_new = 1 - ss_res/ss_tot
    rmse_new = np.sqrt(np.mean((wave-wave_pred_new)**2))
except Exception as e:
    print(f"Fit failed: {e}")
    A_fit, B_fit, C_fit = CALIB_A, CALIB_B, CALIB_C
    wave_pred_new = model((tec,mw,dist), A_fit, B_fit, C_fit)
    r2_new = rmse_new = None

# Frozen model predictions
wave_pred_frozen = model((tec,mw,dist), CALIB_A, CALIB_B, CALIB_C)
ss_res_f = np.sum((wave - wave_pred_frozen)**2)
ss_tot_f = np.sum((wave - np.mean(wave))**2)
r2_frozen = 1 - ss_res_f/ss_tot_f
rmse_frozen = np.sqrt(np.mean((wave-wave_pred_frozen)**2))

# ── Print results ─────────────────────────────────────────────────
print("="*60)
print("UPDATED CALIBRATION — FAR-FIELD MODEL")
print("="*60)
print(f"\nDataset: {len(CALIB)} confirmed detections with tide gauge data")
print(f"\nFROZEN model (A={CALIB_A:.3f}, B={CALIB_B:.3f}, C={CALIB_C:.3f}):")
print(f"  r² = {r2_frozen:.3f}  RMSE = {rmse_frozen:.3f}m")
print(f"\nUPDATED fit (A={A_fit:.3f}, B={B_fit:.3f}, C={C_fit:.3f}):")
if r2_new: print(f"  r² = {r2_new:.3f}  RMSE = {rmse_new:.3f}m")

print(f"\n{'Event':<20} {'Actual':>8} {'Frozen':>8} {'Updated':>8} {'Err%':>7}")
print("-"*55)
for i,c in enumerate(CALIB):
    err_f = (wave_pred_frozen[i]-wave[i])/wave[i]*100
    err_n = (wave_pred_new[i]-wave[i])/wave[i]*100
    print(f"  {c['name']:<18} {wave[i]:>7.3f}m "
          f"{wave_pred_frozen[i]:>7.3f}m "
          f"{wave_pred_new[i]:>7.3f}m "
          f"{err_n:>+6.0f}%")

print(f"\nMEAN ABSOLUTE ERROR:")
print(f"  Frozen model: {np.mean(np.abs(wave_pred_frozen-wave)/wave)*100:.1f}%")
print(f"  Updated fit:  {np.mean(np.abs(wave_pred_new-wave)/wave)*100:.1f}%")

print(f"\n{'='*60}")
print("DETECTION LIMITS CHARACTERIZATION")
print(f"{'='*60}")
print(f"\nEvents that did not detect — characterizing system boundaries:")
for lim in LIMITS:
    print(f"  {lim['name']:<15} Mw={lim['mw']}  wave≈{lim['wave']:.3f}m  → {lim['reason']}")

print(f"\nInferred detection thresholds:")
print(f"  Minimum wave amplitude:  ~0.3-0.4m at Hawaii for reliable detection")
print(f"  Maximum detection range: ~10,000-11,000km at 2.0σ threshold")
print(f"  Time-of-day sensitivity: Late UTC quakes push window into daytime ionosphere")
print(f"  MKEA altitude effect:    3,763m elevation → elevated false trigger rate daytime")

# ── Plot ──────────────────────────────────────────────────────────
fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

# Panel 1: Predicted vs actual
ax = axes[0]
colors_c = ["#D85A30","#185FA5","#BA7517","#0F6E56"]
for i,c in enumerate(CALIB):
    ax.scatter(wave[i], wave_pred_frozen[i], color=colors_c[i], s=120,
               zorder=5, label=c['name'], marker='o')
    ax.scatter(wave[i], wave_pred_new[i], color=colors_c[i], s=80,
               zorder=5, marker='^', alpha=0.7)
    ax.annotate(c['name'], (wave[i], wave_pred_frozen[i]),
                textcoords="offset points", xytext=(6,4),
                fontsize=7.5, color=colors_c[i])

lims = [0, 1.5]
ax.plot(lims, lims, 'k--', alpha=0.4, linewidth=1, label='Perfect')
ax.plot(lims, [l*0.5 for l in lims], 'gray', alpha=0.3, linewidth=1, linestyle=':')
ax.plot(lims, [l*2.0 for l in lims], 'gray', alpha=0.3, linewidth=1, linestyle=':')
ax.fill_between(lims, [l*0.5 for l in lims], [l*2.0 for l in lims],
                alpha=0.05, color='green', label='Factor-of-2 band')

# Circles = frozen, triangles = updated
from matplotlib.lines import Line2D
legend_elements = [
    Line2D([0],[0],marker='o',color='gray',ms=8,label=f'Frozen model (r²={r2_frozen:.3f})'),
    Line2D([0],[0],marker='^',color='gray',ms=8,label=f'Updated fit (r²={r2_new:.3f})',alpha=0.7),
    Line2D([0],[0],color='k',linestyle='--',alpha=0.4,label='Perfect prediction'),
]
ax.legend(handles=legend_elements, fontsize=8, loc='upper left')
ax.set_xlabel("Actual wave height at Hilo (m)", fontsize=10)
ax.set_ylabel("Predicted wave height (m)", fontsize=10)
ax.set_title("Calibration Model: Predicted vs Actual\nCircles=frozen, Triangles=updated fit",
             fontsize=10, fontweight='bold')
ax.set_xlim(0, 1.5); ax.set_ylim(0, 1.5)
ax.grid(alpha=0.2)

# Panel 2: Detection envelope
ax = axes[1]
# Plot all events by Mw vs wave height, colored by detection status
det_events = [
    ("Tōhoku 2011",    9.0, 1.318, "detected",     "#D85A30"),
    ("Chile 2010",     8.8, 0.464, "detected",     "#BA7517"),
    ("Kuril 2006",     8.3, 0.418, "detected",     "#0F6E56"),
    ("Haida Gwaii",    7.7, 0.653, "detected",     "#185FA5"),
    ("Tonga 2022",     None,None,  "detected_sp",  "#8E44AD"),
    ("Kuril 2007",     8.1, 0.105, "missed_amp",   "#888888"),
    ("Peru 2001",      8.4, 0.282, "missed_time",  "#888888"),
    ("Samoa 2009",     8.1, 0.20,  "missed_geo",   "#AAAAAA"),
    ("Sumatra 2004",   9.1, 0.40,  "missed_range", "#CCCCCC"),
]

markers = {"detected":"o","detected_sp":"*","missed_amp":"x",
           "missed_time":"x","missed_geo":"^","missed_range":"s"}
ms = {"detected":100,"detected_sp":180,"missed_amp":100,
      "missed_time":100,"missed_geo":80,"missed_range":80}
labels = {"detected":"✓ Detected","missed_amp":"✗ Below amplitude threshold",
          "missed_time":"✗ Daytime masking","missed_geo":"− No upstream anchor",
          "missed_range":"− Range limit","detected_sp":"✓ Detected (special)"}

plotted = set()
for name,mw_v,wave_v,status,col in det_events:
    if mw_v is None or wave_v is None: continue
    lbl = labels.get(status,"") if status not in plotted else ""
    plotted.add(status)
    ax.scatter(mw_v, wave_v, color=col, s=ms[status],
               marker=markers[status], zorder=5,
               label=lbl if lbl else None, linewidths=1.5,
               edgecolors='white' if status=='detected' else col)
    ax.annotate(name, (mw_v, wave_v), textcoords="offset points",
                xytext=(5,4), fontsize=7.5, color=col)

# Detection boundary lines
ax.axhline(0.30, color='green', linestyle='--', alpha=0.6, linewidth=1.2,
           label='~Min detectable wave (~0.3m)')
ax.fill_between([7.5,9.5],[0,0],[0.30,0.30], alpha=0.07, color='red',
                label='Below detection threshold')

ax.set_xlabel("Earthquake magnitude (Mw)", fontsize=10)
ax.set_ylabel("Wave height at Hilo (m)", fontsize=10)
ax.set_title("Detection Envelope\nEvent outcomes by magnitude and wave height",
             fontsize=10, fontweight='bold')
ax.set_xlim(7.4, 9.4); ax.set_ylim(0, 1.5)
ax.legend(fontsize=7.5, loc='upper left'); ax.grid(alpha=0.2)

fig.suptitle("Updated Calibration Analysis — All Events\n"
             "n=4 confirmed detections  |  n=4 detection-limit characterizations",
             fontsize=11, fontweight='bold')
plt.tight_layout()
plt.savefig("calibration_updated.png", dpi=150)
plt.close()

print(f"\nSaved calibration_updated.png")
print(f"Upload: calibration_updated.png")
