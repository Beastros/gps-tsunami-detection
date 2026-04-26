"""
Pipeline Health Check
======================
Verifies all components are correctly configured and online.
Run anytime to confirm the system is healthy.

  python health_check.py

Green = good. Yellow = warning. Red = action needed.
Last updated: V4 session (April 26 2026)
"""

import os
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

# -- Colors ---------------------------------------------------------
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}OK{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}WN{RESET}  {msg}")
def fail(msg): print(f"  {RED}XX{RESET}  {msg}")
def info(msg): print(f"  {CYAN}->{RESET}  {msg}")
def head(msg): print(f"\n{BOLD}{msg}{RESET}")

issues = []

# -- 1. Required files ----------------------------------------------
head("[ 1 ] Required files")
REQUIRED = [
    "pipeline.py",
    "usgs_listener.py",
    "rinex_downloader.py",
    "detector_runner.py",
    "scorer.py",
    "dart_checker.py",
    "space_weather.py",
    "ionosonde_checker.py",
    "notify.py",
    "notify_discord.py",
    "backtest.py",
    "adaptive_thresholds.py",
    "health_check.py",
    "run_and_push.bat",
]
for f in REQUIRED:
    if Path(f).exists():
        ok(f)
    else:
        fail(f"{f} -- MISSING")
        issues.append(f"Missing file: {f}")

# -- 2. .env credentials --------------------------------------------
head("[ 2 ] Credentials (.env)")
env_path = Path(".env")
env_lines = {}
if not env_path.exists():
    fail(".env file not found")
    issues.append("No .env file")
else:
    raw = env_path.read_bytes()
    content = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
    env_lines = {l.split("=")[0].strip(): l.split("=", 1)[1].strip()
                 for l in content.splitlines() if "=" in l and not l.strip().startswith("#")}

    # Earthdata
    user = env_lines.get("EARTHDATA_USER", "")
    pwd  = env_lines.get("EARTHDATA_PASS", "")
    ok(f"EARTHDATA_USER = {user}") if user else (fail("EARTHDATA_USER not set"), issues.append("Missing EARTHDATA_USER"))
    ok(f"EARTHDATA_PASS = {'*' * len(pwd)}") if pwd else (fail("EARTHDATA_PASS not set"), issues.append("Missing EARTHDATA_PASS"))

    # Email notify
    email = env_lines.get("NOTIFY_EMAIL", "")
    apwd  = env_lines.get("NOTIFY_APP_PASSWORD", "")
    ok(f"NOTIFY_EMAIL = {email}") if email else warn("NOTIFY_EMAIL not set -- email alerts disabled")
    ok(f"NOTIFY_APP_PASSWORD = {'*' * len(apwd)}") if apwd else warn("NOTIFY_APP_PASSWORD not set -- email alerts disabled")

    # Discord webhook
    webhook = env_lines.get("DISCORD_WEBHOOK_URL", "")
    if not webhook:
        fail("DISCORD_WEBHOOK_URL not set -- Discord alerts disabled")
        issues.append("Missing DISCORD_WEBHOOK_URL")
    elif "discord.com/api/webhooks/" not in webhook:
        fail("DISCORD_WEBHOOK_URL looks malformed")
        issues.append("Malformed DISCORD_WEBHOOK_URL")
    else:
        ok(f"DISCORD_WEBHOOK_URL = ...{webhook[-12:]}")
        # Warn if it looks like the exposed April 26 URL (any URL set before regen reminder)
        info("Reminder: regenerate webhook if it was visible in any chat session")

    # Corruption check
    bad = [l for l in content.splitlines() if "Out-File" in l or "Add-Content" in l]
    if bad:
        fail(".env contains PowerShell commands -- recreate it")
        issues.append(".env corrupted with PS commands")

# -- 3. USGS feed ---------------------------------------------------
head("[ 3 ] USGS Earthquake Feed")
try:
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        count = len(data.get("features", []))
        ok(f"USGS feed reachable -- {count} events in past week")
except Exception as e:
    fail(f"USGS feed unreachable: {e}")
    issues.append("Cannot reach USGS feed")

# -- 4. NASA CDDIS --------------------------------------------------
head("[ 4 ] NASA CDDIS Archive")
try:
    url = "https://cddis.nasa.gov/archive/gps/data/daily/"
    req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        ok("CDDIS archive reachable")
except urllib.error.HTTPError as e:
    if e.code in [401, 403]:
        ok("CDDIS reachable (auth required -- expected)")
    else:
        warn(f"CDDIS returned HTTP {e.code}")
        issues.append(f"CDDIS HTTP {e.code}")
except Exception as e:
    fail(f"CDDIS unreachable: {e}")
    issues.append("Cannot reach CDDIS")

# -- 5. NOAA tide gauge ---------------------------------------------
head("[ 5 ] NOAA Tide Gauge API")
try:
    url = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
           "?product=water_level&application=health_check"
           "&begin_date=20240101&end_date=20240101"
           "&datum=MLLW&station=1617760&time_zone=GMT"
           "&units=metric&interval=h&format=json")
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        if "data" in data:
            ok("NOAA CO-OPS API reachable -- Hilo gauge responding")
        else:
            warn(f"NOAA response unexpected: {data.get('error','?')}")
except Exception as e:
    fail(f"NOAA API unreachable: {e}")
    issues.append("Cannot reach NOAA API")

# -- 6. NOAA SWPC space weather feeds --------------------------------
head("[ 6 ] NOAA SWPC Space Weather Feeds")
SWPC_FEEDS = [
    ("Kp index",     "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"),
    ("Solar wind",   "https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"),
    ("IMF Bz",       "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json"),
    ("GOES X-ray",   "https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"),
]
for name, url in SWPC_FEEDS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            ok(f"SWPC {name} -- {len(data)} records")
    except Exception as e:
        fail(f"SWPC {name} unreachable: {e}")
        issues.append(f"Cannot reach SWPC {name}")

# -- 7. NOAA NDBC / DART buoy API -----------------------------------
head("[ 7 ] NOAA NDBC / DART Buoy API")
TEST_BUOYS = [("51407", "Hawaii"), ("46402", "Gulf of Alaska"), ("32412", "Chile")]
for buoy_id, label in TEST_BUOYS:
    try:
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.dart"
        req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="ignore")
            lines = [l for l in raw.splitlines()
                     if l.strip() and not l.startswith("#") and not l.startswith("Y")]
            ok(f"DART buoy {buoy_id} ({label}) -- {len(lines)} records")
    except urllib.error.HTTPError as e:
        warn(f"DART buoy {buoy_id} ({label}) -- HTTP {e.code} (may be offline)")
    except Exception as e:
        fail(f"DART buoy {buoy_id} unreachable: {e}")
        issues.append(f"Cannot reach NDBC DART API (buoy {buoy_id})")

# dart_checker.py import
try:
    import dart_checker
    ok(f"dart_checker imported -- {len(dart_checker.DART_BUOYS)} buoys configured")
except Exception as e:
    fail(f"dart_checker import error: {e}")
    issues.append("dart_checker.py import failed")

# -- 8. GIRO ionosonde API ------------------------------------------
head("[ 8 ] GIRO Digisonde / Ionosonde API")
GIRO_STATIONS = [
    ("GU513", "Guam"),
    ("WP937", "Wake Island"),
    ("KJ609", "Kwajalein"),
]
giro_ok = 0
for sid, label in GIRO_STATIONS:
    try:
        url = (f"https://lgdc.uml.edu/common/DIDBGetValues"
               f"?ursiCode={sid}&charName=foF2&DMUF=3000&fromDate=2024-01-01+00%3A00%3A00"
               f"&toDate=2024-01-01+06%3A00%3A00&fmt=JSONf")
        req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
        with urllib.request.urlopen(req, timeout=12) as r:
            raw = r.read().decode("utf-8", errors="ignore")
            if "Records" in raw or "values" in raw.lower() or len(raw) > 50:
                ok(f"GIRO {sid} ({label}) -- responding")
                giro_ok += 1
            else:
                warn(f"GIRO {sid} ({label}) -- empty response (normal for old dates)")
                giro_ok += 1
    except Exception as e:
        warn(f"GIRO {sid} ({label}) -- {e}")
if giro_ok == 0:
    fail("No GIRO stations responding")
    issues.append("GIRO API unreachable")

try:
    import ionosonde_checker
    stations = getattr(ionosonde_checker, "IONOSONDE_STATIONS", {})
    ok(f"ionosonde_checker imported -- {len(stations)} stations configured")
except Exception as e:
    fail(f"ionosonde_checker import error: {e}")
    issues.append("ionosonde_checker.py import failed")

# -- 9. Discord webhook ---------------------------------------------
head("[ 9 ] Discord Webhook")
webhook = env_lines.get("DISCORD_WEBHOOK_URL", "")
if not webhook:
    warn("DISCORD_WEBHOOK_URL not in .env -- skipping connectivity test")
elif "discord.com/api/webhooks/" not in webhook:
    fail("DISCORD_WEBHOOK_URL malformed -- cannot test")
    issues.append("Discord webhook URL malformed")
else:
    try:
        # HEAD-style check: GET the webhook info endpoint (returns 200 + JSON with no message sent)
        req = urllib.request.Request(webhook, headers={"User-Agent": "gps-tsunami-health-check"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            name = data.get("name", "?")
            ok(f"Discord webhook valid -- channel: '{name}'")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            fail("Discord webhook returns 401 -- URL invalid or deleted, regenerate it")
            issues.append("Discord webhook invalid -- regenerate DISCORD_WEBHOOK_URL")
        else:
            warn(f"Discord webhook HTTP {e.code}")
    except Exception as e:
        warn(f"Discord webhook check error: {e}")

# -- 10. GitHub repo + dashboard ------------------------------------
head("[ 10 ] GitHub Repository & Dashboard")
try:
    url = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/running_log.json"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        scored = len(data.get("scored_events", []))
        ok(f"running_log.json accessible -- {scored} scored events")
except Exception as e:
    fail(f"running_log.json not accessible: {e}")
    issues.append("running_log.json missing from GitHub")

try:
    url = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/poll_log.json"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        polls = data.get("total_polls", 0)
        last  = data.get("last_updated", "?")[:16]
        ok(f"poll_log.json accessible -- {polls} polls, last: {last}")
except Exception as e:
    fail(f"poll_log.json not accessible: {e}")
    issues.append("poll_log.json missing from GitHub")

try:
    url = "https://beastros.github.io/gps-tsunami-detection/"
    with urllib.request.urlopen(url, timeout=10) as r:
        html = r.read().decode("utf-8", errors="ignore")
        if "GPS Tsunami" in html:
            ok("Dashboard live at beastros.github.io/gps-tsunami-detection/")
        else:
            warn("Dashboard reachable but content unexpected")
except Exception as e:
    fail(f"Dashboard unreachable: {e}")
    issues.append("Dashboard not loading")

# -- 11. Git repo / push health -------------------------------------
head("[ 11 ] Git Repo / Push Health")
REPO = Path(r"C:\Users\Mike\Desktop\repo")
if REPO.exists():
    ok("Repo folder found")
    try:
        log = subprocess.run(["git", "-C", str(REPO), "log", "--oneline", "-1"],
                             capture_output=True, text=True, timeout=10)
        if log.returncode == 0:
            ok(f"Last commit: {log.stdout.strip()}")
        status = subprocess.run(["git", "-C", str(REPO), "status", "--short"],
                                capture_output=True, text=True, timeout=10)
        if status.stdout.strip():
            warn("Uncommitted changes in repo -- push may be stale")
            issues.append("Repo has uncommitted changes")
        else:
            ok("Repo working tree clean")
        remote = subprocess.run(["git", "-C", str(REPO), "ls-remote", "--heads", "origin"],
                                capture_output=True, text=True, timeout=15)
        if remote.returncode == 0:
            ok("GitHub remote reachable -- credentials working")
        else:
            fail("Cannot reach GitHub remote -- git push will fail")
            issues.append("Git remote unreachable")
    except Exception as e:
        warn(f"Git check error: {e}")
else:
    fail(f"Repo folder not found: {REPO}")
    issues.append("Repo folder missing")

# -- 12. Station network integrity ----------------------------------
head("[ 12 ] GPS Station Network (V4)")
EXPECTED_STATIONS = ["mkea", "kokb", "hnlc", "guam", "chat", "thti", "thtg",
                     "auck", "noum", "kwj1", "holb"]
detector_file = Path("detector_runner.py")
if detector_file.exists():
    content = detector_file.read_text(encoding="utf-8")
    for sid in EXPECTED_STATIONS:
        if f'"{sid}"' in content:
            ok(f"Station {sid.upper()} present in detector_runner.py")
        else:
            fail(f"Station {sid.upper()} MISSING from detector_runner.py")
            issues.append(f"Missing station: {sid.upper()}")
else:
    warn("detector_runner.py not found -- skipping station check")

EXPECTED_CORRIDORS = ["auck", "noum", "kwj1", "holb"]
rinex_file = Path("rinex_downloader.py")
if rinex_file.exists():
    content = rinex_file.read_text(encoding="utf-8")
    for sid in EXPECTED_CORRIDORS:
        if f'"{sid}"' in content:
            ok(f"Station {sid.upper()} present in CORRIDOR_STATIONS")
        else:
            fail(f"Station {sid.upper()} MISSING from rinex_downloader.py CORRIDOR_STATIONS")
            issues.append(f"Missing corridor station: {sid.upper()}")
else:
    warn("rinex_downloader.py not found -- skipping corridor check")

# -- 13. Adaptive thresholds ----------------------------------------
head("[ 13 ] Adaptive Thresholds")
recs_file = Path("threshold_recommendations.json")
if recs_file.exists():
    try:
        recs = json.loads(recs_file.read_text(encoding="utf-8"))
        n_tp    = recs.get("n_tp_total", 0)
        run_utc = recs.get("run_utc", "?")[:16]
        ok(f"threshold_recommendations.json found -- {n_tp} TP observations, last run {run_utc}")
        if n_tp < 10:
            info(f"Only {n_tp} TP observations -- recommendations advisory, do not apply yet")
    except Exception as e:
        warn(f"threshold_recommendations.json parse error: {e}")
else:
    warn("threshold_recommendations.json not found -- run adaptive_thresholds.py once")
    issues.append("threshold_recommendations.json missing -- run adaptive_thresholds.py")

# -- 14. Event queue ------------------------------------------------
head("[ 14 ] Event Queue")
queue_file = Path("event_queue.json")
if queue_file.exists():
    try:
        q = json.loads(queue_file.read_text())
        events  = q.get("events", [])
        seen    = len(q.get("seen_ids", []))
        pending = [e for e in events if e.get("status") not in ["scored"]]
        scored  = [e for e in events if e.get("status") == "scored"]
        ok(f"event_queue.json found -- {seen} USGS IDs checked")
        ok(f"{len(events)} total events: {len(pending)} pending, {len(scored)} scored")
        if pending:
            info("Pending events:")
            for e in pending[:3]:
                info(f"  Mw{e.get('magnitude','?')} {e.get('place','?')[:40]} "
                     f"status={e.get('status','?')}")
    except Exception as e:
        warn(f"event_queue.json parse error: {e}")
else:
    warn("event_queue.json not found -- run pipeline.py --once first")
    issues.append("No event queue")

# -- 15. Poll log freshness -----------------------------------------
head("[ 15 ] Poll Log Freshness")
PIPELINE_DIR = Path(r"C:\Users\Mike\Desktop\Earthquake Feed Listener Engine")
for candidate in [REPO / "poll_log.json", PIPELINE_DIR / "poll_log.json", Path("poll_log.json")]:
    if candidate.exists():
        poll_file = candidate
        break
else:
    poll_file = None

if poll_file:
    try:
        p = json.loads(poll_file.read_text())
        polls = p.get("polls", [])
        if polls:
            last_ts = datetime.fromisoformat(polls[-1]["ts"].replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
            if age_min < 20:
                ok(f"Last poll {age_min:.0f} min ago -- pipeline running")
            elif age_min < 60:
                warn(f"Last poll {age_min:.0f} min ago -- may have missed a cycle")
                issues.append(f"Poll gap: {age_min:.0f} min")
            else:
                fail(f"Last poll {age_min:.0f} min ago -- pipeline may be down")
                issues.append("Pipeline appears stopped")
        else:
            warn("poll_log.json empty -- run pipeline.py --once")
    except Exception as e:
        warn(f"poll_log.json parse error: {e}")
else:
    warn("poll_log.json not found locally")

# -- 16. Task Scheduler ---------------------------------------------
head("[ 16 ] Windows Task Scheduler")
TASK_NAME = "GPS Tsunami Master"
BAT_FILE  = PIPELINE_DIR / "run_and_push.bat"
ok("run_and_push.bat found") if BAT_FILE.exists() else (
    fail(f"run_and_push.bat missing"), issues.append("run_and_push.bat not found"))
try:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST"],
        capture_output=True, text=True, timeout=10)
    if result.returncode == 0:
        lines    = result.stdout.strip().splitlines()
        status   = next((l.split(":", 1)[1].strip() for l in lines if "Status"   in l), "?")
        next_run = next((l.split(":", 1)[1].strip() for l in lines if "Next Run" in l), "?")
        last_run = next((l.split(":", 1)[1].strip() for l in lines if "Last Run" in l), "?")
        if status.lower() in ["ready", "running"]:
            ok(f"Task '{TASK_NAME}': {status}")
            ok(f"Last run: {last_run}  |  Next run: {next_run}")
        else:
            warn(f"Task '{TASK_NAME}' status: {status}")
            issues.append(f"Scheduler status: {status}")
    else:
        fail(f"Task '{TASK_NAME}' not found in Task Scheduler")
        issues.append("Task Scheduler not configured")
except Exception as e:
    warn(f"Could not check Task Scheduler: {e}")

# -- 17. Python dependencies ----------------------------------------
head("[ 17 ] Python Dependencies")
DEPS = ["numpy", "scipy", "pandas", "matplotlib", "georinex", "ncompress", "requests"]
for dep in DEPS:
    try:
        __import__(dep)
        ok(dep)
    except ImportError:
        fail(f"{dep} -- NOT INSTALLED  (pip install {dep})")
        issues.append(f"Missing package: {dep}")

# -- Summary --------------------------------------------------------
print(f"\n{'='*55}")
if not issues:
    print(f"{GREEN}{BOLD}  ALL SYSTEMS OPERATIONAL{RESET}")
    print(f"{DIM}  Pipeline healthy. Monitoring Pacific basin.{RESET}")
else:
    print(f"{YELLOW}{BOLD}  {len(issues)} ISSUE(S) FOUND:{RESET}")
    for i, issue in enumerate(issues, 1):
        print(f"  {RED}{i}.{RESET} {issue}")
print(f"{'='*55}\n")
