"""
Pipeline Health Check
======================
Verifies all components are correctly configured and online.
Run anytime to confirm the system is healthy.

  python health_check.py

Green = good. Yellow = warning. Red = action needed.
"""

import os
import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Colors ─────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
DIM    = "\033[2m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}✓{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}⚠{RESET}  {msg}")
def fail(msg): print(f"  {RED}✗{RESET}  {msg}")
def info(msg): print(f"  {CYAN}→{RESET}  {msg}")
def head(msg): print(f"\n{BOLD}{msg}{RESET}")

issues = []

# ── 1. Required files ─────────────────────────────────────────────
head("[ 1 ] Required files")
REQUIRED = [
    "pipeline.py",
    "usgs_listener.py",
    "rinex_downloader.py",
    "detector_runner.py",
    "scorer.py",
]
for f in REQUIRED:
    if Path(f).exists():
        ok(f)
    else:
        fail(f"{f} — MISSING")
        issues.append(f"Missing file: {f}")

# ── 2. .env credentials ───────────────────────────────────────────
head("[ 2 ] Credentials (.env)")
env_path = Path(".env")
if not env_path.exists():
    fail(".env file not found")
    issues.append("No .env file")
else:
    raw = env_path.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        content = raw[3:].decode('utf-8')
    else:
        content = raw.decode('utf-8')

    lines = {l.split('=')[0].strip(): l.split('=',1)[1].strip()
             for l in content.splitlines() if '=' in l}

    user = lines.get('EARTHDATA_USER','')
    pwd  = lines.get('EARTHDATA_PASS','')

    if user:
        ok(f"EARTHDATA_USER = {user}")
    else:
        fail("EARTHDATA_USER not set")
        issues.append("Missing EARTHDATA_USER")

    if pwd:
        ok(f"EARTHDATA_PASS = {'*' * len(pwd)}")
    else:
        fail("EARTHDATA_PASS not set")
        issues.append("Missing EARTHDATA_PASS")

    # Check for leftover commands in .env
    bad_lines = [l for l in content.splitlines()
                 if l.strip() and 'Out-File' in l or 'Add-Content' in l]
    if bad_lines:
        fail(".env contains PowerShell commands — recreate it")
        issues.append(".env file corrupted with PS commands")

# ── 3. USGS feed connectivity ─────────────────────────────────────
head("[ 3 ] USGS Earthquake Feed")
try:
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
    req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        count = len(data.get("features", []))
        ok(f"USGS feed reachable — {count} events in past week")
except Exception as e:
    fail(f"USGS feed unreachable: {e}")
    issues.append("Cannot reach USGS feed")

# ── 4. NASA CDDIS connectivity ────────────────────────────────────
head("[ 4 ] NASA CDDIS Archive")
try:
    url = "https://cddis.nasa.gov/archive/gps/data/daily/"
    req = urllib.request.Request(url, headers={"User-Agent": "gps-tsunami-health-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        ok("CDDIS archive reachable")
except urllib.error.HTTPError as e:
    if e.code in [401, 403]:
        ok("CDDIS reachable (auth required — expected)")
    else:
        warn(f"CDDIS returned HTTP {e.code}")
        issues.append(f"CDDIS HTTP {e.code}")
except Exception as e:
    fail(f"CDDIS unreachable: {e}")
    issues.append("Cannot reach CDDIS")

# ── 5. NOAA tide gauge ────────────────────────────────────────────
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
            ok("NOAA CO-OPS API reachable — Hilo gauge responding")
        else:
            warn(f"NOAA response unexpected: {data.get('error','?')}")
except Exception as e:
    fail(f"NOAA API unreachable: {e}")
    issues.append("Cannot reach NOAA API")

# ── 6. GitHub repo + dashboard ────────────────────────────────────
head("[ 6 ] GitHub Repository")
try:
    url = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/running_log.json"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        scored = len(data.get("scored_events", []))
        ok(f"running_log.json accessible — {scored} scored events")
except Exception as e:
    fail(f"running_log.json not accessible: {e}")
    issues.append("running_log.json missing from GitHub")

try:
    url = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/poll_log.json"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        polls = data.get("total_polls", 0)
        last  = data.get("last_updated","?")[:16]
        ok(f"poll_log.json accessible — {polls} polls, last: {last}")
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

# ── 7. Event queue ────────────────────────────────────────────────
head("[ 7 ] Event Queue")
queue_file = Path("event_queue.json")
if queue_file.exists():
    try:
        q = json.loads(queue_file.read_text())
        events = q.get("events", [])
        seen   = len(q.get("seen_ids", []))
        pending = [e for e in events if e.get("status") not in ["scored"]]
        scored  = [e for e in events if e.get("status") == "scored"]
        ok(f"event_queue.json found — {seen} USGS IDs checked")
        ok(f"{len(events)} total events: {len(pending)} pending, {len(scored)} scored")
        if pending:
            info(f"Pending events:")
            for e in pending[:3]:
                info(f"  Mw{e.get('magnitude','?')} {e.get('place','?')[:40]} "
                     f"status={e.get('status','?')}")
    except Exception as e:
        warn(f"event_queue.json parse error: {e}")
else:
    warn("event_queue.json not found — run pipeline.py --once first")
    issues.append("No event queue")

# ── 8. Poll log freshness ─────────────────────────────────────────
head("[ 8 ] Poll Log Freshness")
poll_file = Path("poll_log.json")
if poll_file.exists():
    try:
        p = json.loads(poll_file.read_text())
        polls = p.get("polls", [])
        if polls:
            last_poll = polls[-1]
            last_ts = datetime.fromisoformat(
                last_poll["ts"].replace("Z","+00:00"))
            age_min = (datetime.now(timezone.utc) - last_ts).total_seconds() / 60
            if age_min < 20:
                ok(f"Last poll {age_min:.0f} min ago — pipeline running")
            elif age_min < 60:
                warn(f"Last poll {age_min:.0f} min ago — may have missed a cycle")
                issues.append(f"Poll gap: {age_min:.0f} min")
            else:
                fail(f"Last poll {age_min:.0f} min ago — pipeline may be down")
                issues.append("Pipeline appears stopped")
        else:
            warn("poll_log.json empty — run pipeline.py --once")
    except Exception as e:
        warn(f"poll_log.json parse error: {e}")
else:
    warn("poll_log.json not found locally")

# ── 9. Windows Task Scheduler ─────────────────────────────────────
head("[ 9 ] Task Scheduler")
try:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", "GPS Tsunami Pipeline", "/fo", "LIST"],
        capture_output=True, text=True, timeout=10
    )
    if result.returncode == 0:
        lines = result.stdout.strip().splitlines()
        status = next((l.split(":",1)[1].strip() for l in lines if "Status" in l), "?")
        next_run = next((l.split(":",1)[1].strip() for l in lines if "Next Run" in l), "?")
        if status.lower() in ["ready","running"]:
            ok(f"Task Scheduler: {status} — next run: {next_run}")
        else:
            warn(f"Task Scheduler status: {status}")
            issues.append(f"Scheduler status: {status}")
    else:
        warn("Task 'GPS Tsunami Pipeline' not found in scheduler")
        info("Set it up: Task Scheduler → Create Task → repeat every 15 min")
        issues.append("Task Scheduler not configured")
except Exception as e:
    warn(f"Could not check Task Scheduler: {e}")

# ── 10. Python dependencies ───────────────────────────────────────
head("[ 10 ] Python Dependencies")
deps = ["numpy","scipy","pandas","matplotlib","georinex","ncompress","requests"]
for dep in deps:
    try:
        __import__(dep)
        ok(dep)
    except ImportError:
        fail(f"{dep} — NOT INSTALLED  (pip install {dep})")
        issues.append(f"Missing package: {dep}")

# ── Summary ───────────────────────────────────────────────────────
print(f"\n{'='*55}")
if not issues:
    print(f"{GREEN}{BOLD}  ALL SYSTEMS OPERATIONAL{RESET}")
    print(f"{DIM}  Pipeline healthy. Monitoring Pacific basin.{RESET}")
else:
    print(f"{YELLOW}{BOLD}  {len(issues)} ISSUE(S) FOUND:{RESET}")
    for i, issue in enumerate(issues, 1):
        print(f"  {RED}{i}.{RESET} {issue}")
print(f"{'='*55}\n")
