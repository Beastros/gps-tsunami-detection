# GPS Ionospheric Tsunami Detection
## Project Master Plan & Continuation Document — v7
Last updated: April 28, 2026 (V6 session)  |  Status: LIVE — 7-channel fusion + fast poll mode  |  github.com/Beastros/gps-tsunami-detection

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
- Use Copy-Item not copy /Y in PowerShell for file copies
- pipeline.py has a BOM — always open with utf-8-sig encoding in patch scripts

**Common pitfalls learned (see CLAUDE_CODE_RULES.md for full list):**
- Downloads folder caches old files — always self-delete in deploy scripts
- NASA CDDIS auth: basic auth doesn't survive redirect — use _EarthdataSession session class
- Windows cp1252 terminal: Unicode in log messages silently crashes station processing loop
- Notepad adds BOM to .env — load .env manually with BOM stripping, not python-dotenv
- detector_runner.py bare except in station loop catches UnicodeEncodeError silently
- window_pairs pair names are LOWERCASE — zone constraint dict keys need .upper() lookup
- Set-Content -Encoding utf8 adds BOM and mangles emoji — always use Python for file writes
- Health check patches: verify with $p.Contains() before assuming they applied
- pipeline.py has a BOM: open with encoding="utf-8-sig" in any patch script
- Never use Wikipedia or web search for same-day seismic events — query USGS API directly
- copy /Y is CMD syntax — use Copy-Item in PowerShell

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
- **Fast poll mode: drops to 2-min cycles for 2 hours when any Mw6.0+ Pacific event detected**
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

# Current System State (April 28, 2026 — post V6)

## Infrastructure

- Machine: DESKTOP-HEUSVDU, Windows 10, user Mike
- Pipeline: C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\
- Repo: C:\Users\Mike\Desktop\repo\ → github.com/Beastros/gps-tsunami-detection
- Dashboard: beastros.github.io/gps-tsunami-detection/ (4 tabs: Dashboard, Events, Poll Log, About)
- Task Scheduler: 'GPS Tsunami Master' every 15 min as SYSTEM
- Credentials in .env: EARTHDATA_USER=mthhorn, NOTIFY_EMAIL=mthhorn@gmail.com
- DISCORD_WEBHOOK_URL in .env: REGENERATE if exposed in any session chat
- Poll count: 315+ polls since launch, 0 scored live events (awaiting first Pacific qualifying event)
- Google Analytics: G-E6L8R0GG76 — tracking dashboard traffic
- Pipeline launched: April 23, 2026. Both Mw7.4 qualifying events (April 1 Bitung, April 20 Miyako) predate launch — nothing missed.

## Pipeline Files

| File | Purpose | Status |
|---|---|---|
| pipeline.py | Master orchestrator + fast poll loop | LIVE — fast poll added V6 |
| usgs_listener.py | Polls USGS, focal mechanism filter, fast poll trigger | LIVE — fast poll trigger V6 |
| rinex_downloader.py | Downloads RINEX from NASA CDDIS | LIVE — Earthdata session auth fixed V3 |
| detector_runner.py | 7-channel TEC detector + zone constraints | LIVE — explicit None constraints V6 |
| scorer.py | Binary + confidence scoring | LIVE — v2 scorer |
| dart_checker.py | 28 DART buoys | LIVE |
| space_weather.py | 4-channel NOAA SWPC quality score | LIVE — V2 |
| ionosonde_checker.py | GIRO DIDBase foF2 anomaly detection | LIVE — V2 |
| notify.py | Gmail email alert | LIVE |
| notify_discord.py | Discord webhook alerting | LIVE — V3 |
| backtest.py | Historical backtester | LIVE — V3 |
| health_check.py | 21-section system verification | LIVE — V6 section 21 zone constraints |
| adaptive_thresholds.py | Bayesian threshold recommender | LIVE — V4 |
| run_and_push.bat | Task Scheduler target | LIVE |
| fast_poll.json | Fast poll state file (pipeline folder only) | Written by usgs_listener on Mw6.0+ Pacific |
| CLAUDE_CODE_RULES.md | Environment reference — rules 1-28 | V6 |
| index.html | Dashboard — 4 tabs, color-coded GPS, alert banner | V6 |

## Fast Poll Mode (added V6)
- Trigger: Any Mw >= 6.0 event in any Pacific zone (lower than 6.5 qualify threshold — catches magnitude upgrades)
- Behavior: pipeline.py --once loops internally at 2-min intervals instead of exiting
- Duration: 2 hours from trigger, then returns to normal 15-min Task Scheduler cadence
- State file: fast_poll.json in pipeline folder (not committed to GitHub)
- Git push cadence: still every 15 min via run_and_push.bat

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
| MKEA | Mauna Kea HI | 19.801 | -155.456 | 3763 | None (explicit) |
| KOKB | Kokee Kauai HI | 22.127 | -159.665 | 1167 | None (explicit) |
| HNLC | Honolulu HI | 21.297 | -157.816 | 5 | None (explicit) |
| GUAM | Guam | 13.489 | 144.868 | 83 | None (explicit) |
| CHAT | Chatham Islands NZ | -43.956 | -176.566 | 63 | None (explicit) |
| THTI/THTG | Tahiti | -17.577 | -149.606 | 87 | None (explicit) |
| AUCK | Auckland NZ | -36.602 | 174.834 | 106 | None (explicit) |
| NOUM | Noumea NC | -22.270 | 166.413 | 69 | None (explicit) |
| KWJ1 | Kwajalein Marshall Islands | 8.722 | 167.730 | 39 | None (explicit) |
| HOLB | Holberg BC Canada | 50.640 | -128.133 | 180 | **Cascadia only: lat 40–52, lon -135 to -120** |

Health check section 21 verifies all stations have explicit entries in STATION_ZONE_CONSTRAINTS. Adding a new station without an entry triggers a red failure.

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
Fixed: HOLB geographic zone constraint — FPR restored to 0.00. Dashboard: About tab, footer, UTF-8 mojibake fixed, Google Analytics added. Health check section 21. CLAUDE_CODE_RULES.md rules 1-26.

## V6 (April 28, 2026)
- **Fast poll mode**: usgs_listener.py writes fast_poll.json on Mw6.0+ Pacific detection; pipeline.py loops at 2-min intervals for 2 hours. Proxy for ShakeAlert (no public API available).
- **Dashboard overhaul**: 10 GPS stations now color-coded by region (cyan/blue/sky=Hawaii, gold=GUAM, amber=KWJ1, mint/teal=SW Pacific, purple/pink=SE Pacific, coral=HOLB Cascadia). DART buoys changed to bright blue (#0abde3), ionosondes to bright yellow (#ffd32a), near-miss seismic remains orange (#ffa726) — all 3 now visually distinct.
- **Hawaii cluster**: KOKB/HNLC/MKEA labels fan out with dotted SVG leader lines.
- **Red alert banner**: appears between header and tabs when event_queue.json has active unscored events; live badge flips red "ALERT · FAST POLL".
- **Active detection crosshair**: 3 pulsing concentric red rings + crosshair lines rendered at epicenter coordinates.
- **health_check section 21**: zone constraint integrity check — all 11 stations now have explicit entries (10 None + 1 HOLB constraint).
- **Explicit None zone constraints**: all unconstrained stations now have explicit None in STATION_ZONE_CONSTRAINTS.
- **README v6**: fully rewritten — 7-channel fusion, V5 backtest, 10-station network, 21-section health check.
- **CLAUDE_CODE_RULES.md v6**: rules 27-28 added (BOM/utf-8-sig, Copy-Item), USGS direct query rule, V6 session history.
- Fixed duplicate initMap() call in index.html.
- Pipeline at 315+ polls, 0 scored live events. Both April 2026 Mw7.4 events (Bitung Apr 1, Miyako Apr 20) predate pipeline launch Apr 23.

---

# V7 Development Roadmap

## Priority 1: Watch for first live qualifying event
- Pipeline is running, no action needed
- Fast poll mode will fire automatically on Mw6.0+ Pacific detection
- When scored: check threshold_recommendations.json for Bayesian update advice

## Priority 2: DYFI Integration (NEXT SESSION TASK)
**USGS "Did You Feel It" crowdsourced reports — implement dyfi_checker.py**

ShakeAlert has no public API. DYFI is the best available fast pre-TEC channel.

**What it provides:**
- Available 5–15 min post-earthquake (before ShakeMap moment tensor is finalized)
- Fields: response count, max CDI (Community Decimal Intensity 1–10), geographic spread
- High CDI (7+) at coastal stations = strong thrust indicator
- Available via USGS event detail API already fetched by usgs_listener.py

**API:** DYFI data lives inside the existing USGS event detail geojson:
```
GET https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{usgs_id}.geojson
products.dyfi[0].properties:
  num-responses   → response count
  maxmmi          → max Modified Mercalli Intensity
  feltreports     → felt report count
```

**Confidence contribution (proposed):**
```
dyfi_contrib = +0.04 if num_responses >= 50 AND maxmmi >= 6
             = +0.02 if num_responses >= 20 AND maxmmi >= 5
             = 0     if insufficient data (fail-open)
```
Small contribution — DYFI is a corroboration signal, not a primary channel.
Fail-open: no DYFI data = dyfi_confirmed=False, no penalty.

**Caveat:** DYFI is heavily biased toward US/Japan/NZ populations. Remote Pacific events will have low response counts regardless of magnitude. Weight should abstain (return 0) below 20 responses rather than penalize.

**Implementation plan:**
1. Create dyfi_checker.py — fetches DYFI data from USGS event detail geojson
2. Add dyfi_contrib to combined_confidence formula in detector_runner.py
3. Add DYFI status field to event_queue entries
4. Surface DYFI response count on dashboard event cards
5. Add dyfi_checker to health_check section 22

**Rail 2 concept (future, not next session):**
When fast_poll fires on Mw6.0+ event, begin DART/ionosonde polling immediately before full qualification. DYFI at T+8min could serve as the early gate for this. Hold for first live event to understand real timing bottlenecks before adding this complexity.

## Priority 3: ML Classifier
BLOCKED until ~30 scored live events.

## Priority 4: Publication (NHESS Technical Note)
BLOCKED until ~10 scored live events.

## Priority 5: Zone constraint validator in health_check
DONE — section 21 added V6.

## Future Sensor Expansion (ideas only)
- AIS vessel tracking — free via AISHub/MarineTraffic basic tier
- CTBTO hydroacoustic — underwater T-wave detection, requires institutional access (post-publication)
- Infrasound networks — some university public access
- Path to premium data: publish NHESS Technical Note → credibility → data sharing agreements

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

## HOLB Cross-Basin Spurious Pairs (FIXED V5)
- _pair_zone_ok() filter restricts HOLB to Cascadia epicenters (lat 40–52, lon -135 to -120)
- pair names are lowercase — constraint uses .upper() for lookup

## Discord Webhook
- REGENERATE if URL was visible in any session chat
- Update DISCORD_WEBHOOK_URL in .env after regenerating

## task_runner.log vs pipeline.log
- task_runner.log: written by run_and_push.bat every 15-min cycle (the live log)

## running_log.json
- Only updates on scored events — perpetually "stale" by mtime with 0 live events — expected

## pipeline.py BOM
- pipeline.py has a UTF-8 BOM from Notepad editing
- Any patch script reading pipeline.py MUST use encoding="utf-8-sig"

## Seismic event verification
- NEVER use Wikipedia or web search for same-day seismic events
- Query USGS API directly: earthquake.usgs.gov/fdsnws/event/1/query

---

# Quick Reference: Starting Next Session

Copy-paste this to begin:

*This is my GPS ionospheric tsunami detection project. Read this document for full context. Also read CLAUDE_CODE_RULES.md from the repo before writing any code.*

*System is live with a 7-channel sensor fusion pipeline + fast poll mode (2-min cycles on Mw6.0+ Pacific detection). V6 complete: color-coded GPS stations, red alert banner + crosshair on active event, DART/ionosonde/seismic distinct colors, Hawaii cluster leader lines, health check section 21 zone constraint integrity, explicit None zone constraints, README v6, CLAUDE_CODE_RULES v6 rules 1-28. Pipeline at 315+ polls, 0 scored live events, all systems operational.*

*Next task for V7: Implement DYFI (Did You Feel It) integration. Build dyfi_checker.py using the USGS event detail geojson (products.dyfi), add small confidence contribution (+0.02 to +0.04) to combined_confidence in detector_runner.py, surface DYFI response count on dashboard, add to health_check section 22. See V7 Roadmap in this doc for full spec including API fields and proposed contribution weights. ShakeAlert has no public API — fast poll mode is our proxy. DYFI is the next real channel.*
