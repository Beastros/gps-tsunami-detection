# GPS Ionospheric Tsunami Detection

A Kp-gated multi-station coherence detector for Pacific tsunami early warning using GPS Total Electron Content (TEC) perturbations.

**Independent research project.** All data sourced from free public archives. All code open source.

🌊 **Live Dashboard**: [beastros.github.io/gps-tsunami-detection](https://beastros.github.io/gps-tsunami-detection/)

---

## What This Does

When a tsunami travels across the open ocean, it generates an atmospheric gravity wave (AGW) that propagates upward to the ionosphere (~300 km altitude) and disturbs the electron density. GPS satellites broadcast signals through this region — by comparing two frequencies from the same satellite, a receiver can measure the disturbance as a TEC (Total Electron Content) perturbation.

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
| Kp gate | < 4.0 (real-time NOAA SWPC fetch) |
| Time-of-day sensitivity | Late UTC quakes (>18:00) reduced probability |

---

## Live Pipeline

The operational pipeline monitors USGS in real time, downloads GPS data, runs the frozen detector, and scores predictions against a network of NOAA tide gauges automatically every 15 minutes.

### Pipeline Stages

```
[1] USGS listener    — polls Mw6.5+ Pacific earthquakes every 15 min
[2] RINEX downloader — fetches GPS observation files from NASA CDDIS
[3] Detector runner  — runs frozen coherence detector, fetches real-time Kp
[4] Scorer           — checks 4 tide gauges 24h post-event, writes score
```

### Scoring — Tide Gauge Network

Predictions are verified against four NOAA CO-OPS stations:

| Station | ID | Location | Role |
|---------|-----|----------|------|
| Hilo, HI | 1617760 | 19.73°N 155.09°W | Primary |
| Midway Atoll | 1619910 | 28.21°N 177.36°W | Secondary |
| Johnston Atoll | 1619543 | 16.74°N 169.53°W | Secondary |
| Pago Pago, AS | 1770000 | 14.28°S 170.69°W | Secondary |

Secondary gauges rescue geometry-limited misses — if Hilo shows no signal but a secondary gauge confirms a wave and the algorithm detected, the event scores as TRUE_POSITIVE rather than FALSE_POSITIVE.

### Outcome Classification

| Outcome | Meaning |
|---------|---------|
| TRUE_POSITIVE | Algorithm detected, gauge confirmed wave |
| TRUE_NEGATIVE | Algorithm quiet, no wave at any gauge |
| FALSE_POSITIVE | Algorithm detected, no wave at any gauge |
| FALSE_NEGATIVE | Algorithm missed, wave confirmed at gauge |
| GEOMETRY_LIMITED_MISS | No anchor station geometry — abstention correct |
| CORRECT_ABSTENTION_NO_ANCHOR | No anchor available, correctly abstained |

### Kp Contamination Filter

At runtime, the detector fetches the current planetary K-index from NOAA Space Weather (SWPC). If Kp ≥ 4.0 at the time of the event, the detection window is flagged as potentially geomagnetically contaminated and the event is gated — no detection is issued regardless of TEC signal strength. This prevents false positives during geomagnetic storms, which produce ionospheric perturbations visually indistinguishable from tsunami AGW signals.

### Email Alerts

The pipeline sends an email alert to the configured address when a qualifying event enters the queue, including magnitude, location, TEC detection window, estimated lead time, and anchor station geometry.

### Running the Pipeline

```bash
# Run one cycle manually:
python pipeline.py --once

# Run continuously (every 15 min — normally handled by Task Scheduler):
python pipeline.py

# Verify all components are healthy:
python health_check.py
```

### Environment Setup

Requires a `.env` file in the pipeline directory (never committed to git):

```
EARTHDATA_USER=your_nasa_earthdata_username
EARTHDATA_PASS=your_nasa_earthdata_password
NOTIFY_EMAIL=your_email@gmail.com
NOTIFY_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

`EARTHDATA_*` credentials are for NASA CDDIS RINEX access (free account at urs.earthdata.nasa.gov).
`NOTIFY_APP_PASSWORD` is a Gmail App Password (not your Gmail password) — generate at myaccount.google.com/apppasswords.

---

## Repository Structure

```
# Live operational pipeline
pipeline.py               # Master orchestrator — runs all 4 stages
usgs_listener.py          # Polls USGS every 15 min, catches Pacific Mw6.5+ events
rinex_downloader.py       # Downloads RINEX from NASA CDDIS when event queued
detector_runner.py        # Runs frozen detector, fetches real-time Kp from NOAA SWPC
scorer.py                 # Scores prediction vs 4-gauge NOAA tide gauge network
notify.py                 # Email alerts on qualifying event detection
health_check.py           # Verifies all pipeline components are online

# Live data (auto-updated every 15 min by pipeline)
running_log.json          # Append-only scored event log — read by dashboard
poll_log.json             # USGS poll history — read by dashboard
event_queue.json          # Internal event state tracker

# Dashboard
index.html                # Live dashboard — hosted on GitHub Pages

# Historical validation scripts
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

## Requirements

```
python >= 3.8
numpy scipy pandas matplotlib georinex ncompress requests
```

```bash
pip install numpy scipy pandas matplotlib georinex ncompress requests
```

---

## Data Sources (all free)

| Source | Data | URL |
|--------|------|-----|
| NASA CDDIS | RINEX GPS observations | cddis.nasa.gov/archive/gps/data/daily/ |
| NOAA CO-OPS | Tide gauge water level | api.tidesandcurrents.noaa.gov |
| NOAA SWPC | Real-time Kp index | services.swpc.noaa.gov |
| USGS | Real-time earthquake feed | earthquake.usgs.gov/earthquakes/feed |

---

## Health Check

The `health_check.py` script verifies all pipeline components in one run:

```
[ 1 ] Required files present
[ 2 ] Credentials (.env) loaded
[ 3 ] USGS earthquake feed reachable
[ 4 ] NASA CDDIS archive reachable
[ 5 ] NOAA tide gauge API responding
[ 6 ] GitHub repository and dashboard accessible
[6b ] Git repo push health and credential check
[ 7 ] Event queue status
[ 8 ] Poll log freshness (flags if >20 min since last run)
[ 9 ] Windows Task Scheduler task status
[10 ] Python dependencies installed
```

---

## Key Findings

1. **Long-baseline coherence eliminates 94–98% of false alarms.** Single-station processing produces 29–131 false triggers per day; the coherence requirement reduces this to zero across all tested control days.

2. **Network geometry is the primary detection variable.** Each Pacific source zone requires a specific upstream station. Station placement matters more than signal processing sophistication.

3. **Pierce-point-weighted stacking degrades accuracy.** Equal-weight median stacking outperforms PPW by an average of 54 percentage points in wave height prediction error. The median's outlier resistance outweighs the geometric advantage of pierce-point alignment.

4. **Detection range limit ~10,000–11,000 km at 2.0σ.** Sumatra 2004 (Mw 9.1) produced strong GUAM signals but Hawaii was silent at 11,800 km.

5. **Method extends to volcanic eruptions.** Tonga 2022 detected via atmospheric Lamb wave at 292 m/s, +1.7 hours post-eruption.

6. **Multi-gauge ground truth improves scoring reliability.** Four-station tide gauge network reduces geometry-limited misclassifications and provides corroborating evidence for borderline detections.

---

## Status

- [x] Core detector validated (TPR=1.00, FPR=0.00)
- [x] Calibration model (r²=0.988)
- [x] Blind validation on held-out events
- [x] Detection envelope characterized
- [x] Cascading prediction demonstrated
- [x] Live operational pipeline running (15-min poll cycle)
- [x] Real-time Kp contamination gate (NOAA SWPC)
- [x] Multi-gauge scoring network (Hilo, Midway, Johnston, Pago Pago)
- [x] Email alerts on qualifying events
- [x] Public dashboard with live scoring log
- [ ] Paper submission (target: NHESS Technical Note)
- [ ] Station-specific calibration for upstream anchors (CHAT, GUAM)
- [ ] Multi-station TEC coherence (v2)
- [ ] Tsunamigenicity classifier (v2, requires ~30 scored events)

---

*Parameters frozen 2025-04-22. All results reproducible from publicly available data.*
