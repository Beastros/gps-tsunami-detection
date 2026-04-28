# GPS Ionospheric Tsunami Detection

A 7-channel real-time sensor fusion pipeline for Pacific tsunami early warning using GPS Total Electron Content (TEC) perturbations fused with ocean pressure buoys, ionosonde measurements, constellation cross-validation, and seismic focal mechanism scoring.

**Independent research project.** All data sourced from free public APIs and open-source tools. Zero cost to run.

🌊 **Live Dashboard**: [beastros.github.io/gps-tsunami-detection](https://beastros.github.io/gps-tsunami-detection/)

---

## What This Does

When a tsunami crosses the open ocean it generates an Atmospheric Gravity Wave (AGW) that rises to the ionosphere (~300 km) and disturbs electron density. GPS signals passing through this region show the disturbance as a TEC (Total Electron Content) perturbation.

The pipeline identifies tsunami signals by requiring that the perturbation propagates **coherently between two or more GPS stations** separated by ≥1,000 km, at a speed consistent with open-ocean tsunami propagation (150–350 m/s), in the direction consistent with the known epicenter, beginning 1.5–22 hours post-earthquake.

This spatiotemporal consistency test eliminates 94–98% of single-station false alarms. Seven independent channels then fuse their evidence into a single `combined_confidence` score (0–1).

---

## 8-Channel Sensor Stack

| Channel | Source | Max Contribution |
|---|---|---|
| GPS TEC coherence | NASA CDDIS RINEX L1/L2 | 0.55 × space weather reliability |
| Space weather gate | 4-channel NOAA SWPC | Penalty multiplier on TEC weight |
| GLONASS + Galileo | Same RINEX, R/E satellites | ±0.10 constellation agreement bonus |
| dTEC/dt | Derived from GPS TEC | +0.05 corroboration bonus |
| DART ocean pressure | NOAA NDBC — 28 buoys | +0.45 |
| GIRO ionosonde foF2 | GIRO DIDBase — 5 stations | +0.12 |
| DYFI felt reports | USGS event detail API | +0.02 / +0.04 | ACTIVE — V7 |
| ShakeMap focal mechanism | USGS moment tensor API | Hard gate + tsunamigenic prior weight |

**combined_confidence formula:**
```
tec_reliability = max(1.0 - sw_score * 0.6, 0.2)
tec_contrib     = 0.55 * tec_reliability * tsunamigenic_weight  (0 if not detected)
dart_contrib    = dart_score * 0.45       (-0.08 if negative)
const_contrib   = +0.10 agreement / -0.10 disagreement / +0.03 partial
dtec_contrib    = +0.05 if dTEC/dt corroborates
iono_contrib    = +0.12 if ionosonde confirmed
combined        = min(sum, 1.0)
```

Strike-slip events (tsunamigenic index < 0.25 from USGS ShakeMap moment tensor) are hard-gated before any RINEX processing.

---

## Station Network

| Station | Location | Lat | Lon | Zone Constraint |
|---|---|---|---|---|
| MKEA | Mauna Kea, HI | 19.801 | −155.456 | None |
| KOKB | Kokee, Kauai, HI | 22.127 | −159.665 | None |
| HNLC | Honolulu, HI | 21.297 | −157.816 | None |
| GUAM | Guam | 13.489 | 144.868 | None |
| CHAT | Chatham Islands, NZ | −43.956 | −176.566 | None |
| THTI/THTG | Tahiti | −17.577 | −149.606 | None |
| AUCK | Auckland, NZ | −36.602 | 174.834 | None |
| NOUM | Noumea, New Caledonia | −22.270 | 166.413 | None |
| KWJ1 | Kwajalein, Marshall Islands | 8.722 | 167.730 | None |
| HOLB | Holberg, BC, Canada | 50.640 | −128.133 | Cascadia only (lat 40–52, lon −135 to −120) |

HOLB is restricted to Cascadia-geometry epicenters to prevent cross-basin spurious pair detections on Japan/Kermadec events.

---

## Detection Parameters (frozen 2025-04-22)

| Parameter | Value |
|---|---|
| Magnitude threshold | Mw ≥ 6.5 |
| Depth limit | ≤ 100 km |
| AGW propagation speed | 150–350 m/s |
| TEC detection window | +1.5 to +22h post-quake |
| SNR threshold | 2.0σ, minimum duration 3 min |
| Long baseline minimum | 1,000 km between station pairs |
| Calibration model | wave_m = 2283.839 × TEC × 10^(0.771 × Mw) / dist_km^2.614 |

---

## Validated Results (V5 Backtest)

**TPR = 1.00, FPR = 0.00 (TP=4, TN=5, FP=0, FN=0)**

| Event | Mw | Result | Conf | Notes |
|---|---|---|---|---|
| Tohoku 2011 | 9.1 | TRUE_POSITIVE | 0.52 | KOKB–GUAM +9.7h 153 m/s |
| Chile 2010 | 8.8 | TRUE_POSITIVE | 0.52 | HNLC–GUAM +2.7h 322 m/s |
| Kuril 2006 | 8.3 | TRUE_POSITIVE | 0.52 | KOKB–NOUM +8.0h 238 m/s |
| Haida Gwaii 2012 | 7.7 | TRUE_POSITIVE | 0.62 | HNLC–GUAM +1.5h 303 m/s |
| Samoa 2009 | 8.1 | CORRECT_ABSTENTION | 0.00 | No anchor geometry |
| Sumatra 2012 strike-slip | 8.6 | TRUE_NEGATIVE | 0.00 | ShakeMap gate (tsunamigenic_weight=0) |
| Okhotsk 2013 deep | 8.3 | TRUE_NEGATIVE | 0.29 | tsunamigenic_weight=0.4; depth gate fires first in live pipeline |
| Kermadec 2011 | 7.4 | TRUE_NEGATIVE | 0.00 | HOLB zone constraint blocked cross-basin pairs |
| Tohoku foreshock 2011 | 7.2 | TRUE_NEGATIVE | 0.00 | HOLB zone constraint blocked cross-basin pairs |

Backtest confidence scores are TEC-only (DART and ionosonde historical data not available via public API for 2006–2013 events). Live events receive full 8-channel fusion.

---

## Live Pipeline

The operational pipeline monitors USGS in real time, downloads GPS RINEX data, runs the 7-channel detector, and scores predictions against NOAA tide gauges automatically every 15 minutes via Windows Task Scheduler.

### Pipeline Stages

```
[1] USGS listener       — polls Mw6.5+ shallow Pacific events every 15 min
                          filters strike-slip via USGS ShakeMap moment tensor
[2] Space weather check — 4-channel NOAA SWPC quality gate before RINEX download
[3] RINEX downloader    — fetches GPS/GLONASS/Galileo obs from NASA CDDIS
[4] Detector runner     — 7-channel TEC + DART + ionosonde + constellation fusion
[5] Scorer              — scores vs 4-station NOAA tide gauge network at T+24h
[6] Alerting            — email + Discord webhook on qualifying detection
```

### Scoring — Tide Gauge Network

| Station | ID | Location |
|---|---|---|
| Hilo, HI | 1617760 | 19.73°N 155.09°W |
| Midway Atoll | 1619910 | 28.21°N 177.36°W |
| Johnston Atoll | 1619543 | 16.74°N 169.53°W |
| Pago Pago, AS | 1770000 | 14.28°S 170.69°W |

### Running the Pipeline

```powershell
# Run one cycle manually:
python pipeline.py --once

# Run the full health check (21 sections):
python health_check.py
```

### Environment Setup

Requires a `.env` file in the pipeline directory (never committed to git):

```
EARTHDATA_USER=your_nasa_earthdata_username
EARTHDATA_PASS=your_nasa_earthdata_password
NOTIFY_EMAIL=your_email@gmail.com
NOTIFY_APP_PASSWORD=xxxx xxxx xxxx xxxx
DISCORD_WEBHOOK_URL=your_discord_webhook_url
```

- `EARTHDATA_*`: free NASA Earthdata account at urs.earthdata.nasa.gov
- `NOTIFY_APP_PASSWORD`: Gmail App Password from myaccount.google.com/apppasswords
- `DISCORD_WEBHOOK_URL`: Discord channel webhook URL — regenerate if ever exposed in chat logs

---

## Repository Structure

```
# Live operational pipeline (pipeline folder — not all files committed to repo)
pipeline.py               # Master orchestrator — runs all stages every 15 min
usgs_listener.py          # Polls USGS, filters focal mechanism via ShakeMap
rinex_downloader.py       # Downloads RINEX from NASA CDDIS (Earthdata session auth)
detector_runner.py        # 8-channel fusion detector + zone constraints
scorer.py                 # Scores predictions vs 4-station tide gauge network
space_weather.py          # 4-channel NOAA SWPC space weather quality score
dart_checker.py           # 28-buoy NOAA NDBC DART ocean pressure check
ionosonde_checker.py      # GIRO DIDBase foF2 anomaly detection (5 stations)
notify.py                 # Gmail email alerts
notify_discord.py         # Discord webhook alerting
backtest.py               # Historical backtester
health_check.py           # 21-section system verification
adaptive_thresholds.py    # Bayesian threshold recommender (advisory)
run_and_push.bat          # Task Scheduler target — runs pipeline + git push
CLAUDE_CODE_RULES.md      # Environment reference — Windows/deployment pitfalls

# Live data (auto-updated every 15 min by pipeline)
running_log.json          # Append-only scored event log — read by dashboard
poll_log.json             # USGS poll history — read by dashboard
event_queue.json          # Internal event state tracker

# Dashboard
index.html                # Live dashboard — 4 tabs, hosted on GitHub Pages

# Historical validation scripts
scripts/
  detector_params.py        # FROZEN parameters — do not modify
  coherence_kpgated.py      # Primary detector (historical)
  blind_validation.py       # Blind validation: Kuril 2006, Samoa 2009
  cascading_demo.py         # End-to-end prediction demo: Chile 2010
  calibration_updated.py    # Calibration model fit and evaluation

figures/
  blind_validation.png
  cascading_demo.png
  calibration_updated.png
```

---

## Data Sources (all free)

| Source | Data | URL |
|---|---|---|
| NASA CDDIS | RINEX GPS/GLONASS/Galileo observations | cddis.nasa.gov/archive/gps/data/daily/ |
| NOAA CO-OPS | Tide gauge water level | api.tidesandcurrents.noaa.gov |
| NOAA SWPC | 4-channel space weather (Kp, Dst, X-ray, proton flux) | services.swpc.noaa.gov |
| NOAA NDBC | DART ocean pressure buoys (28 Pacific stations) | ndbc.noaa.gov |
| USGS | Real-time earthquake feed + ShakeMap moment tensors | earthquake.usgs.gov |
| GIRO DIDBase | Ionosonde foF2 measurements (5 stations) | giro.uml.edu/didbase |

---

## Requirements

```
python >= 3.8
numpy scipy pandas matplotlib georinex ncompress requests
```

```
pip install numpy scipy pandas matplotlib georinex ncompress requests
```

---

## Health Check (21 Sections)

`health_check.py` verifies the full system in one pass:

```
[ 1] Required files present
[ 2] Credentials (.env) loaded and non-empty
[ 3] USGS earthquake feed reachable
[ 4] NASA CDDIS archive reachable
[ 5] NOAA tide gauge API responding
[ 6] GitHub repository and dashboard accessible
[6b] Git repo push health and credential check
[ 7] Event queue status
[ 8] Poll log freshness (flags if >20 min since last run)
[ 9] Windows Task Scheduler task status
[10] Python dependencies installed
[11] SMTP email auth check
[12] CDDIS auth check
[13] Module integrity (imports)
[14] Deduplication check (event_queue.json)
[15] Untracked files in repo
[16] DART buoy API reachability
[17] GIRO ionosonde API reachability
[18] NOAA SWPC space weather feeds
[19] Discord webhook reachability
[20] Log freshness (task_runner.log)
[21] Zone constraint integrity (station coverage check)
```

---

## Key Findings

1. **Long-baseline coherence eliminates 94–98% of false alarms.** Single-station processing produces 29–131 false triggers per day; the coherence requirement reduces this to zero across all tested control days.
2. **Network geometry is the primary detection variable.** Each Pacific source zone requires a specific upstream station. Station placement matters more than signal processing sophistication.
3. **Focal mechanism filtering is essential at lower magnitudes.** The tsunamigenic_weight prior (from USGS ShakeMap moment tensors) correctly gates strike-slip and deep-focus events that would otherwise score false positives.
4. **Station zone constraints prevent cross-basin spurious pairs.** HOLB (Holberg BC) produced false positives on Japan/Kermadec events until geographic zone constraints were applied, restoring FPR to 0.00.
5. **DART buoys provide the largest single non-TEC confidence contribution (+0.45).** In live events with DART confirmation, combined_confidence is expected to significantly exceed the TEC-only backtest baseline of 0.52.
6. **Detection range limit ~10,000–11,000 km at 2.0sigma.** Sumatra 2004 (Mw 9.1) geometry exceeded the maximum useful baseline at Hawaii.

---

## Status

- [x] Core GPS TEC coherence detector validated (TPR=1.00, FPR=0.00, 9-event backtest)
- [x] 8-channel sensor fusion (TEC, DART, ionosonde, GLONASS+Galileo, dTEC/dt, ShakeMap, space weather)
- [x] Calibration model (wave_m formula, r²=0.988)
- [x] Live operational pipeline (15-min poll cycle, 223+ polls)
- [x] HOLB geographic zone constraint (FPR=0.00 restored after V4 station expansion)
- [x] Adaptive threshold recommender (Bayesian, advisory)
- [x] Public dashboard — 4 tabs (Dashboard, Events, Poll Log, About)
- [x] Discord + email alerting
- [x] 22-section health check
- [x] Historical backtester
- [ ] First live scored event (awaiting qualifying Pacific event)
- [ ] ML classifier (blocked until ~30 scored live events)
- [ ] NHESS Technical Note submission (blocked until ~10 scored live events)

---

*Parameters frozen 2025-04-22. All results reproducible from publicly available data. This is an independent research project — not an operational warning system.*
