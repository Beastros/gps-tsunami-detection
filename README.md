# GPS Ionospheric Tsunami Detection

A real-time, automated, publicly accessible early-warning research system fusing 7 independent physical measurement channels to detect Pacific tsunamis via GPS ionospheric perturbations.

**Independent research project.** All data sourced from free public archives. All code open source.

🌊 **Live Dashboard**: [beastros.github.io/gps-tsunami-detection](https://beastros.github.io/gps-tsunami-detection/)

---

## How It Works

When a tsunami crosses the open ocean it generates an Atmospheric Gravity Wave (AGW) that propagates upward to the ionosphere (~300 km altitude) and disturbs electron density. GPS signals passing through this region carry the disturbance as a TEC (Total Electron Content) perturbation. The pipeline detects this signal by requiring coherent propagation between station pairs separated by >=1,000 km at speeds consistent with open-ocean tsunami propagation (150-350 m/s), in the direction of the epicenter, beginning 1.5-22 hours post-earthquake.

This spatiotemporal coherence test eliminates 94-98% of single-station false alarms. Six additional independent channels then either corroborate or contradict the TEC signal, each contributing to a fused `combined_confidence` score (0-1).

---

## 7-Channel Sensor Stack

| Channel | Source | Max Contribution | Independence |
|---|---|---|---|
| GPS TEC coherence | NASA CDDIS RINEX L1/L2 | 0.55 x reliability | Primary ionospheric signal |
| Space weather gate | 4 NOAA SWPC feeds | Penalty on TEC weight | Ionospheric quality prior |
| GLONASS + Galileo | Same RINEX, R/E constellations | +/-0.10 agreement bonus | Different satellite systems |
| dTEC/dt rate-of-change | Derived from GPS TEC | +0.05 corroboration | Different feature, same instrument |
| DART ocean pressure | NOAA NDBC -- 28 buoys | +0.45 if confirmed | Completely independent |
| GIRO ionosonde foF2 | GIRO DIDBase -- 5 Pacific stations | +0.12 if confirmed | Independent HF radar |
| ShakeMap focal mechanism | USGS moment tensor API | Hard pre-filter | Removes strike-slip events |

### Confidence Fusion Formula

```
combined_confidence = min(
    tec_contrib          # 0.55 x tec_reliability  (0 if not detected)
  + dart_contrib         # dart_score x 0.45       (-0.08 if negative)
  + const_contrib        # +0.10 agreement / -0.10 disagreement / +0.03 partial
  + dtec_contrib         # +0.05 if dTEC/dt corroborates
  + iono_contrib         # +0.12 if ionosonde confirmed
, 1.0)
```

Example confidence values:
- Clean GPS TEC only: ~0.50
- TEC + 1 DART buoy confirmed: ~0.72
- TEC + 2 DART + GLONASS agreement: ~0.87
- TEC + DART + ionosonde + tri-constellation: ~0.97+
- TEC with contaminated ionosphere (sw=0.5): ~0.33 -- weak, flagged
- GPS-only, GLONASS/Galileo quiet, DART negative: ~0.37 -- near threshold

### Space Weather Quality (4 channels)

The pipeline scores ionospheric conditions before trusting TEC. A high score reduces `tec_reliability` via `max(1.0 - sw_score x 0.6, 0.2)`. A score >= 0.5 gates the event entirely -- RINEX processing is skipped.

| Feed | Source | Threshold |
|---|---|---|
| Kp index (3hr avg) | NOAA SWPC | >=4.0 active, >=6.0 severe |
| IMF Bz (southward) | NOAA SWPC solar wind mag | < -10 nT |
| Solar wind speed | NOAA SWPC solar wind plasma | > 600 km/s |
| GOES X-ray flux | NOAA SWPC GOES primary | >= 1e-5 W/m2 (M-class) |

### ShakeMap Focal Mechanism Filter

Strike-slip earthquakes are not tsunamigenic. Before downloading any GPS data, the pipeline fetches the USGS moment tensor and classifies the rake angle:
- +90 deg (thrust) -> tsunamigenic index 1.0
- -90 deg (normal) -> 0.4
- 0/180 deg (strike-slip) -> 0.0-0.15

Events with index < 0.25 are dropped. The 2012 Sumatra Mw8.6 strike-slip event would score ~0.0 and be skipped. Fail-open: no data = include.

### GIRO Ionosonde Network

Five Pacific Digisonde stations provide independent foF2 (plasma frequency) measurements. Detection: 2.5-sigma threshold, minimum 0.15 MHz delta, in the +1.5 to +20h post-quake window.

| URSI Code | Station | Location |
|---|---|---|
| GU513 | Guam | 13.6N 144.9E |
| KJ609 | Kwajalein | 9.0N 167.7E |
| WP937 | Wake Island | 19.3N 166.6E |
| RP536 | Okinawa | 26.7N 128.2E |
| TW637 | Zhongli, Taiwan | 25.0N 121.2E |

### DART Buoy Network

28 NOAA NDBC DART (Deep-ocean Assessment and Reporting of Tsunamis) buoys are checked for bottom-pressure anomalies. Confirming buoy count maps to confidence score (1 buoy: 0.45, 2 buoys: 0.72, 3+: 0.90), with a sigma boost for strong signals. A negative DART result applies a -0.08 penalty to confidence.

---

## GPS Station Network

| Station | Location | Lat | Lon |
|---|---|---|---|
| MKEA | Mauna Kea, Hawaii | 19.80N | 155.46W |
| KOKB | Kokee, Kauai | 22.13N | 159.67W |
| HNLC | Honolulu | 21.30N | 157.82W |
| GUAM | Guam | 13.49N | 144.87E |
| CHAT | Chatham Islands, NZ | 43.96S | 176.57W |
| THTI | Tahiti | 17.58S | 149.61W |

---

## Calibration Model

```
wave_m = 2283.839 x TEC x 10^(0.771 x Mw) / dist_km^2.614
```

Parameters frozen 2025-04-22 (r2=0.988, mean absolute error 5.3% across four-event calibration set).

---

## Validated Historical Results

| Event | Mw | Result | Method |
|---|---|---|---|
| Haida Gwaii 2012 | 7.7 | Detected | HNLC-GUAM 216 m/s |
| Tohoku 2011 | 9.0 | Detected | KOKB-GUAM 155 m/s |
| Chile 2010 | 8.8 | Detected | KOKB-CHAT 307 m/s -- 108 min lead time |
| Kuril 2006 | 8.3 | Detected | MKEA-GUAM 323 m/s |
| Tonga 2022 (volcanic) | -- | Detected | MKEA-THTG 292 m/s (Lamb wave) |
| Samoa 2009 | 8.1 | Abstain | No anchor station geometry |
| Sumatra 2004 | 9.1 | Abstain | 11,800 km exceeds detection range |
| 11 control days | -- | Silent | 0 false alarms |

**Note:** These results use the V1 GPS-only TEC detector. Full V2 7-channel backtesting is in progress.

**TPR = 1.00, FPR = 0.00** across all geometrically feasible test cases (V1 detector).

---

## Live Pipeline

The operational pipeline polls every 15 minutes on an automated Task Scheduler cycle and pushes results to GitHub Pages continuously.

### Pipeline Stages

```
[1] USGS listener      -- Mw6.5+ Pacific events, focal mechanism pre-filter
[2] RINEX downloader   -- fetches GPS/GLONASS/Galileo RINEX from NASA CDDIS
[3] Detector runner    -- 7-channel sensor fusion, writes combined_confidence
[4] Scorer             -- scores against 4 NOAA tide gauges 24h post-event
```

### Tide Gauge Scoring Network

| Station | ID | Location | Role |
|---|---|---|---|
| Hilo, HI | 1617760 | 19.73N 155.09W | Primary |
| Midway Atoll | 1619910 | 28.21N 177.36W | Secondary |
| Johnston Atoll | 1619543 | 16.74N 169.53W | Secondary |
| Pago Pago, AS | 1770000 | 14.28S 170.69W | Secondary |

### Outcome Classification

| Outcome | Meaning |
|---|---|
| TRUE_POSITIVE | Detected, gauge confirmed wave |
| TRUE_NEGATIVE | Quiet, no wave at any gauge |
| FALSE_POSITIVE | Detected, no wave at any gauge |
| FALSE_NEGATIVE | Missed, wave confirmed at gauge |
| GEOMETRY_LIMITED_MISS | No anchor geometry -- abstention correct |
| CORRECT_ABSTENTION_NO_ANCHOR | No anchor available, correctly abstained |

### Running the Pipeline

```
python pipeline.py --once
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

---

## Requirements

```
pip install numpy scipy pandas matplotlib georinex ncompress requests
```

---

## Data Sources (all free)

| Source | Data | URL |
|---|---|---|
| NASA CDDIS | RINEX GPS/GLONASS/Galileo | cddis.nasa.gov/archive/gps/data/daily/ |
| NOAA CO-OPS | Tide gauge water level | api.tidesandcurrents.noaa.gov |
| NOAA SWPC | Kp, solar wind, X-ray | services.swpc.noaa.gov |
| NOAA NDBC | DART buoy bottom pressure | ndbc.noaa.gov |
| USGS | Earthquake feed + moment tensors | earthquake.usgs.gov |
| GIRO DIDBase | Ionosonde foF2 | lgdc.uml.edu/DIDBase |

---

## Status

- [x] Core GPS TEC detector validated (V1: TPR=1.00, FPR=0.00)
- [x] Calibration model (r2=0.988)
- [x] Live operational pipeline (15-min poll cycle)
- [x] Space weather 4-channel quality gate
- [x] DART 28-buoy ocean pressure network
- [x] GIRO ionosonde foF2 network (5 Pacific stations)
- [x] GLONASS + Galileo multi-constellation agreement
- [x] dTEC/dt rate-of-change channel
- [x] ShakeMap focal mechanism pre-filter
- [x] 7-channel combined_confidence fusion
- [x] Confidence calibration tracking
- [x] Public dashboard with live scoring log
- [ ] Full V2 historical backtesting (in progress)
- [ ] Discord/webhook alerting
- [ ] Station expansion (CORS Pacific, NZ IGS network)
- [ ] Paper submission (target: NHESS Technical Note)

---

*Detection parameters frozen 2025-04-22. All results reproducible from publicly available data.*
*AI assistance disclosure: This project was implemented with the assistance of Claude (Anthropic) per NHESS AI policy.*
