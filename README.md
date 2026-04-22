# GPS Ionospheric Tsunami Detection

A Kp-gated multi-station coherence detector for Pacific tsunami early warning using GPS Total Electron Content (TEC) perturbations.

**Independent research project.** All data sourced from free public archives. All code open source.

---

## What This Does

When a tsunami travels across the open ocean, it generates an atmospheric gravity wave that propagates upward to the ionosphere (~300 km altitude) and disturbs the electron density. GPS satellites broadcast signals through this region — by comparing two frequencies from the same satellite, a receiver can measure the disturbance as a TEC (Total Electron Content) perturbation.

The detector identifies tsunami signals by requiring that the perturbation propagates **coherently between two or more GPS stations** separated by ≥1,000 km, at a speed consistent with open-ocean tsunami propagation (150–350 m/s), in the direction consistent with the known epicenter, beginning 1.5–22 hours post-earthquake, on a geomagnetically quiet day (Kp < 4.0).

This spatiotemporal consistency test eliminates 94–98% of single-station false alarms.

---

## Results

Validated against 18 years of Pacific seismic history:

| Event | Mw | Result | Method |
|-------|----|--------|--------|
| Haida Gwaii 2012 | 7.7 | ✓ Detected | HNLC–GUAM 216 m/s |
| Tōhoku 2011 | 9.0 | ✓ Detected | KOKB–GUAM 155 m/s |
| Chile 2010 | 8.8 | ✓ Detected | KOKB–CHAT 307 m/s |
| Kuril 2006 | 8.3 | ✓ Detected | MKEA–GUAM 323 m/s |
| Tonga 2022 (volcanic) | — | ✓ Detected | MKEA–THTG 292 m/s (Lamb wave) |
| Samoa 2009 | 8.1 | − No anchor | Geometry insufficient |
| Sumatra 2004 | 9.1 | − Range limit | 11,800 km exceeds threshold |
| 11 control days | — | ✓ Silent | 0 false alarms |

**TPR = 1.00, FPR = 0.00** across all geometrically feasible test cases.

**Calibration model**: r²=0.988, mean absolute error 5.3% across the four-event calibration set.

**Cascading prediction demo (Chile 2010)**: CHAT TEC onset at T+13.3h issues a 0.22m forecast at Hilo — 108 minutes before the wave arrives and measures 0.46m.

---

## Calibration Model

```
wave_m = 2283.839 × TEC × 10^(0.771 × Mw) / dist_km^2.614
```

Parameters frozen 2025-04-22. The distance exponent (2.614) reflects geometric spreading; the magnitude exponent (0.771) reflects seismic moment scaling. Both physically motivated and within expected ranges.

---

## Detection Envelope

| Constraint | Threshold |
|------------|-----------|
| Minimum wave height | ~0.3m at Hawaii |
| Maximum epicentral range | ~10,000–11,000 km |
| Upstream anchor required | ≥1,000 km baseline pair |
| Kp gate | < 4.0 |
| Time-of-day sensitivity | Late UTC quakes (>18:00) reduced probability |

---

## Requirements

```
python >= 3.8
numpy scipy pandas matplotlib georinex ncompress
```

```bash
pip install numpy scipy pandas matplotlib georinex ncompress
```

---

## Data Sources (all free)

- **RINEX GPS observations**: [NASA CDDIS](https://cddis.nasa.gov/archive/gps/data/daily/) — requires free Earthdata login
- **Kp geomagnetic index**: [GFZ Potsdam](https://kp.gfz.de)
- **Tide gauge data**: [NOAA CO-OPS API](https://api.tidesandcurrents.noaa.gov)

---

## Repository Structure

```
scripts/
  detector_params.py        # FROZEN parameters — do not modify
  coherence_kpgated.py      # Primary detector (main pipeline)
  blind_validation.py       # Blind validation: Kuril 2006, Samoa 2009
  cascading_demo.py         # End-to-end prediction demo: Chile 2010
  calibration_updated.py    # Calibration model fit and evaluation
  sumatra_tonga.py          # Sumatra 2004 + Tonga 2022
  new_events.py             # Kuril 2007, Peru 2001, Nicobar 2005
  peru_twoday.py            # Two-day RINEX processing for late-UTC events
  pierce_point_weighted.py  # PPW vs equal-weight stacking comparison
  control_day_batch.py      # False alarm characterization on quiet days

figures/
  blind_validation.png
  cascading_demo.png
  calibration_updated.png
  sumatra_tonga.png
  pierce_point_comparison.png
  peru_twoday.png
```

---

## Running

```bash
# Primary detector (Tōhoku, Chile, Haida Gwaii + 11 controls):
python scripts/coherence_kpgated.py

# Blind validation (frozen parameters, held-out events):
python scripts/blind_validation.py

# Cascading prediction demo:
python scripts/cascading_demo.py

# Full calibration analysis:
python scripts/calibration_updated.py
```

RINEX files are not included. Each script documents the exact CDDIS URLs for its required files.

---

## Key Findings

1. **Long-baseline coherence eliminates 94–98% of false alarms.** Single-station processing produces 29–131 false triggers per day; the coherence requirement reduces this to zero.

2. **Network geometry is the primary detection variable.** Each Pacific source zone requires a specific upstream station. Station placement matters more than signal processing sophistication.

3. **Pierce-point-weighted stacking degrades accuracy.** Equal-weight median stacking outperforms PPW by an average of 54 percentage points in wave height prediction error. The median's outlier resistance outweighs the geometric advantage of pierce-point alignment.

4. **Detection range limit ~10,000–11,000 km at 2.0σ.** Sumatra 2004 (Mw 9.1) produced strong GUAM signals but Hawaii was silent at 11,800 km.

5. **Method extends to volcanic eruptions.** Tonga 2022 detected via atmospheric Lamb wave at 292 m/s, +1.7 hours post-eruption.

---

## Status

- [x] Core detector validated (TPR=1.00, FPR=0.00)
- [x] Calibration model (r²=0.988)
- [x] Blind validation on held-out events
- [x] Detection envelope characterized
- [x] Cascading prediction demonstrated
- [ ] Paper submission (target: NHESS)
- [ ] Real-time prototype
- [ ] Station-specific calibration for upstream anchors (CHAT, GUAM)

---

*Parameters frozen 2025-04-22. All results reproducible from publicly available data.*
