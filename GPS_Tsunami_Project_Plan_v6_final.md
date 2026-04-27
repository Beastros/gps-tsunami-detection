# GPS Ionospheric Tsunami Detection
## Project Master Plan & Continuation Document — v6
Last updated: April 26, 2026 (V5 session)  |  Status: LIVE — 7-channel fusion pipeline running  |  github.com/Beastros/gps-tsunami-detection

---

# Instructions for New Claude Session

Paste this document into a new conversation and say:

*This is my GPS ionospheric tsunami detection project. Read this document for full context. Also read CLAUDE_CODE_RULES.md from the repo before writing any code. The system is live and running. Continue from where we left off — next task is [INSERT CURRENT TASK].*

**IMPORTANT: Also read CLAUDE_CODE_RULES.md from the repo before writing any code. It documents environment-specific pitfalls that will save hours of debugging.**

**Always pull the latest file versions from GitHub before modifying.**

- Pipeline folder: C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\
- Git repo folder: C:\Users\Mike\Desktop\repo\
- Task Scheduler: 'GPS Tsunami Master' (every 15 min as SYSTEM)
- Dashboard: beastros.github.io/gps-tsunami-detection/
- GitHub: github.com/Beastros/gps-tsunami-detection (branch: main)

**Deploy pattern (IMPORTANT):**
- ALL deploy scripts must self-delete old Downloads copies at the start
- Bake file content as base64 to avoid download cache issues
- Use Python for all file writes — never PowerShell Set-Content or Out-File for files with non-ASCII
- NEVER use filenames where the base name is a real domain — chat UI linkifies them
- NEVER put .py filenames inside quoted strings in PowerShell commands — use Get-ChildItem wildcard approach
- PowerShell does NOT accept && — run git commands on separate lines
- Always delete stray patch .py files from repo before final commit each session

**Common pitfalls learned (see CLAUDE_CODE_RULES.md for full list):**
- Downloads folder caches old files — always self-delete in deploy scripts
- NASA CDDIS auth: basic auth doesn't survive redirect — use _EarthdataSession session class
- Windows cp1252 terminal: Unicode in log messages silently crashes station processing loop
- Notepad adds BOM to .env — load .env manually with BOM stripping, not python-dotenv
- detector_runner.py bare except in station loop catches UnicodeEncodeError silently
- window_pairs pair names are LOWERCASE — zone constraint dict keys need .upper() lookup
- Set-Content -Encoding utf8 adds BOM and mangles emoji — always use Python for file writes
- Health check patches: verify with $p.Contains() before assuming they applied

---

# Project Goal

Build a real-time, fully automated, publicly accessible GPS ionospheric tsunami early-warning research system that is:

- Novel — fuses 7 independent physical measurement channels no existing system combines in a live automated pipeline
- Scientifically rigorous — auto-scores every prediction against multi-channel ground truth with calibration tracking
- Free — built entirely on public APIs and open-source tools, zero cost to run
- Publishable — targeting NHESS Technical Note after ~10 scored live events with backtesting validation
- Extensible — modular sensor architecture, each channel independently contributes to combined_confidence

---

# How It Works

When a tsunami crosses the open ocean it generates an Atmospheric Gravity Wave (AGW) that rises to the ionosphere (~300 km) and disturbs electron density. GPS signals passing through this region show the disturbance as a TEC (Total Electron Content) perturbation. The 7-channel pipeline:

- Monitors USGS real-time feed for Mw6.5+ shallow Pacific subduction events every 15 min
- Fetches USGS ShakeMap moment tensor — skips strike-slip events (tsunamigenic index < 0.25)
- Checks 4-parameter space weather quality before any RINEX processing
- Downloads GPS RINEX files from NASA CDDIS for upstream anchor stations
- Computes TEC perturbations for GPS, GLONASS, and Galileo constellations independently
- Computes dTEC/dt (rate of change) as a secondary wave-front feature
- Checks 28 DART buoys for ocean pressure anomalies
- Checks 5 GIRO Digisonde stations for independent foF2 perturbations
- Fuses all channels into combined_confidence (0–1)
- Scores predictions 24h later against 4-station NOAA tide gauge network
- Pushes results to GitHub every 15 min — dashboard auto-updates

---

# Current System State (April 26, 2026 — post V5)

## Infrastructure

- Machine: DESKTOP-HEUSVDU, Windows 10, user Mike
- Pipeline: C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\
- Repo: C:\Users\Mike\Desktop\repo\ → github.com/Beastros/gps-tsunami-detection
- Dashboard: beastros.github.io/gps-tsunami-detection/ (4 tabs: Dashboard, Events, Poll Log, About)
- Task Scheduler: 'GPS Tsunami Master' every 15 min as SYSTEM
- Credentials in .env: EARTHDATA_USER=mthhorn, NOTIFY_EMAIL=mthhorn@gmail.com
- DISCORD_WEBHOOK_URL in .env: REGENERATE if exposed in any session chat
- Poll count: 223+ polls since launch, 0 scored live events (awaiting first Pacific qualifying event)
- Google Analytics: G-E6L8R0GG76 — tracking dashboard traffic
- Last commit: V5 session — zone constraint, health check section 21, About tab, footer, GA

## Pipeline Files

| File | Purpose | Status |
|---|---|---|
| pipeline.py | Master orchestrator | LIVE — Discord hook added V3 |
| usgs_listener.py | Polls USGS, focal mechanism filter | LIVE + ShakeMap added |
| rinex_downloader.py | Downloads RINEX from NASA CDDIS | LIVE — Earthdata session auth fixed V3 |
| detector_runner.py | 7-channel TEC detector + zone constraints | LIVE — V5 zone constraint added |
| scorer.py | Binary + confidence scoring | LIVE — v2 scorer |
| dart_checker.py | 28 DART buoys | LIVE |
| space_weather.py | 4-channel NOAA SWPC quality score | LIVE — V2 |
| ionosonde_checker.py | GIRO DIDBase foF2 anomaly detection | LIVE — V2 |
| notify.py | Gmail email alert | LIVE |
| notify_discord.py | Discord webhook alerting | LIVE — V3 |
| backtest.py | Historical backtester | LIVE — V3 |
| health_check.py | 21-section system verification | LIVE — V5 section 21 added |
| adaptive_thresholds.py | Bayesian threshold recommender | LIVE — V4 |
| run_and_push.bat | Task Scheduler target | LIVE |
| CLAUDE_CODE_RULES.md | Environment reference — rules 1-26 | V5 |
| index.html | Dashboard — 4 tabs, footer, GA | V5 |

## Detection Parameters (FROZEN 2025-04-22)

- Magnitude threshold: Mw >= 6.5
- Depth limit: <= 100 km
- AGW propagation speed: 150–350 m/s
- TEC detection window: +1.5 to +22h post-quake
- SNR threshold: 2.0σ, minimum duration 3 min
- Long baseline minimum: 1000 km between station pairs
- Calibration: wave_m = 2283.839 × TEC × 10^(0.771 × Mw) / dist_km^2.614

---

# 7-Channel Sensor Stack

**combined_confidence formula (from detector_runner.py):**

```
tec_reliability = max(1.0 - sw_score * 0.6, 0.2)
tec_contrib     = 0.55 * tec_reliability * tsunamigenic_weight  (0 if not detected)
dart_contrib    = dart_score * 0.45       (-0.08 if negative)
const_contrib   = +0.10 agreement / -0.10 disagreement / +0.03 partial
dtec_contrib    = +0.05 if dTEC/dt corroborates
iono_contrib    = +0.12 if ionosonde confirmed
combined        = min(sum, 1.0)
```

| Channel | Source | Max Contribution | Status |
|---|---|---|---|
| GPS TEC coherence | NASA CDDIS RINEX L1/L2 | 0.55 × reliability | ACTIVE |
| Space weather gate | 4 NOAA SWPC feeds | Penalty on TEC weight | LIVE |
| GLONASS + Galileo | Same RINEX, R/E sats | +0.10 agreement bonus | ACTIVE |
| dTEC/dt | Derived from GPS TEC | +0.05 corroboration | ACTIVE |
| DART ocean pressure | NOAA NDBC — 28 buoys | +0.45 | ACTIVE |
| GIRO ionosonde foF2 | GIRO DIDBase — 5 stations | +0.12 | ACTIVE |
| ShakeMap focal mechanism | USGS moment tensor API | Hard gate + tsunamigenic_weight prior | ACTIVE |

---

# Station Network

| Station | Location | Lat | Lon | Alt (m) | Zone Constraint |
|---|---|---|---|---|---|
| MKEA | Mauna Kea HI | 19.801 | -155.456 | 3763 | None |
| KOKB | Kokee Kauai HI | 22.127 | -159.665 | 1167 | None |
| HNLC | Honolulu HI | 21.297 | -157.816 | 5 | None |
| GUAM | Guam | 13.489 | 144.868 | 83 | None |
| CHAT | Chatham Islands NZ | -43.956 | -176.566 | 63 | None |
| THTI/THTG | Tahiti | -17.577 | -149.606 | 87 | None |
| AUCK | Auckland NZ | -36.602 | 174.834 | 106 | None |
| NOUM | Noumea NC | -22.270 | 166.413 | 69 | None |
| KWJ1 | Kwajalein Marshall Islands | 8.722 | 167.730 | 39 | None |
| HOLB | Holberg BC Canada | 50.640 | -128.133 | 180 | **Cascadia only: lat 40–52, lon -135 to -120** |

---

# Validated Historical Results — V5 Backtest

**V5 Backtest: TPR=1.00, FPR=0.00 (TP=4, TN=5, FP=0, FN=0)**

| Event | Mw | Result | Conf | Notes |
|---|---|---|---|---|
| Tohoku 2011 | 9.1 | TRUE_POSITIVE | 0.52 | KOKB-GUAM +9.7h 153 m/s |
| Chile 2010 | 8.8 | TRUE_POSITIVE | 0.52 | HNLC-GUAM +2.7h 322 m/s |
| Kuril 2006 | 8.3 | TRUE_POSITIVE | 0.52 | KOKB-NOUM +8.0h 238 m/s |
| Haida Gwaii 2012 | 7.7 | TRUE_POSITIVE | 0.62 | HNLC-GUAM +1.5h 303 m/s |
| Samoa 2009 | 8.1 | CORRECT_ABSTENTION | 0.00 | No anchor geometry |
| Sumatra 2012 strike-slip | 8.6 | TRUE_NEGATIVE | 0.00 | TEC coherence test failed |
| Okhotsk 2013 deep | 8.3 | TRUE_NEGATIVE | 0.29 | tsunamigenic_weight=0.4 |
| Kermadec 2011 | 7.4 | TRUE_NEGATIVE | 0.00 | HOLB zone constraint blocked cross-basin pairs |
| Tohoku foreshock 2011 | 7.2 | TRUE_NEGATIVE | 0.00 | HOLB zone constraint blocked cross-basin pairs |

---

# Session History

## V1 (original)
GPS-TEC coherence only. 4-station Kp gate. TPR=1.00, FPR=0.00 on 8 validated events.

## V2 (pre-V3)
Added: DART 28-buoy network, GIRO ionosonde 5 stations, GLONASS+Galileo constellation, dTEC/dt, ShakeMap focal mechanism filter, 4-channel space weather quality score, combined_confidence fusion formula, confidence calibration tracking, V2 scorer.

## V3 (April 26, 2026)
Added: Discord webhook alerting, historical backtester, CDDIS auth fix, README updated to V2, UTF-8 logging fixed.

## V4 (April 26, 2026)
Added: tsunamigenic_weight in combined_confidence, 4 new stations (AUCK/NOUM/KWJ1/HOLB), adaptive_thresholds.py, D3 Natural Earth Pacific map, near-miss seismic markers, health_check expanded to 20 sections. Fixed pipeline.py duplicate imports.

## V5 (April 26, 2026)
Fixed: HOLB geographic zone constraint — prevents cross-basin spurious pairs on Japan/Kermadec events. FPR restored to 0.00. Dashboard: About tab added, footer added with research disclaimer, UTF-8 mojibake fixed. Google Analytics added (G-E6L8R0GG76). Health check section 21 added (zone constraint integrity). CLAUDE_CODE_RULES.md updated to rules 1-26.

---

# Known Issues & Notes

## GIRO Ionosonde
- Historical data (pre-2024) returns empty for most stations — API depth limit
- Fail-open: no data = ionosonde_confirmed=False, no penalty

## DART Buoys
- Historical data unavailable for 2006-2013 events via NDBC API
- All backtest confidence scores are TEC-only (0.52) as a result
- Live events will work

## CDDIS Authentication (FIXED V3)
- _EarthdataSession class in rinex_downloader.py re-sends credentials after redirect
- HTML content detection before saving files

## Detector Unicode Crash (FIXED V3)
- FileHandler uses encoding="utf-8"; Unicode chars replaced with ASCII

## HOLB Cross-Basin Spurious Pairs (FIXED V5)
- _pair_zone_ok() filter restricts HOLB to Cascadia epicenters (lat 40–52, lon -135 to -120)
- pair names are lowercase — constraint uses .upper() for lookup

## Dashboard UTF-8 Mojibake (FIXED V5)
- All index.html writes must use Python — never PowerShell Set-Content
- Emoji/symbol fixes must use raw byte replacement, not Unicode escape strings

## Discord Webhook
- REGENERATE if URL was visible in any session chat
- Update DISCORD_WEBHOOK_URL in .env after regenerating

## task_runner.log vs pipeline.log
- task_runner.log: written by run_and_push.bat every 15-min cycle (the live log)
- Health checks watch task_runner.log

## running_log.json
- Only updates on scored events — perpetually "stale" by mtime with 0 live events — expected

---

# V6 Development Roadmap

## Priority 1: Watch for first live qualifying event
- Pipeline is running, no action needed
- When scored: check threshold_recommendations.json for Bayesian update advice
- First live TP unlocks first real calibration data point
- Monitor Google Analytics (G-E6L8R0GG76) for traffic after Reddit/LinkedIn posts

## Priority 2: ML Classifier
BLOCKED until ~30 scored live events.
- Feature set: TEC amplitude, dTEC/dt peak, onset sharpness, propagation coherence, tsunamigenic_index
- Models: logistic regression → random forest → LSTM

## Priority 3: Publication (NHESS Technical Note)
BLOCKED until ~10 scored live events.
- Target: Natural Hazards and Earth System Sciences
- Need: calibration curve, comparison to baseline GPS-only
- AI assistance disclosure required per NHESS policy

## Priority 4: Zone constraint validator in health_check
- Warn if a new station is added to STATIONS dict without a corresponding zone constraint entry or explicit None
- Prevents future regressions like the HOLB FP issue

V6 Future Expansion Ideas (from V5 session discussion):

AIS vessel tracking — free via AISHub/MarineTraffic basic tier, potential propagation timing reference
CTBTO hydroacoustic network — underwater microphones detecting T-waves, requires institutional access, unlocked by publication
Infrasound networks — atmospheric pressure sensors, some university public access, validated on Tonga 2022 event
USGS "Did You Feel It" crowdsourced reports — public API, rapid focal mechanism corroboration before ShakeMap available
Path to premium data sources: publish NHESS Technical Note after first live scored event, use credibility to request data sharing agreements

---

# Quick Reference: Starting Next Session

Copy-paste this to begin:

*This is my GPS ionospheric tsunami detection project. Read this document for full context. Also read CLAUDE_CODE_RULES.md from the repo before writing any code. The system is live with a 7-channel sensor fusion pipeline running on a 15-minute poll cycle. V5 is complete: HOLB zone constraint (FPR=0.00, TP=4 TN=5 FP=0 FN=0), About tab + footer on dashboard, Google Analytics added, health check 21 sections, CLAUDE_CODE_RULES.md rules 1-26. Next priorities for V6: watch for first live qualifying event, ML classifier blocked until ~30 live events, NHESS publication blocked until ~10 scored live events.*
