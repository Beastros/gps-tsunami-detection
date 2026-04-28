"""
Pipeline Health Check
======================
Comprehensive verification of all pipeline components.
Run anytime to confirm the system is healthy.

  python health_check.py

Green = good. Yellow = warning. Red = action needed.
Last updated: V4 session (April 26 2026)
Sections: 23
"""

import os, json, subprocess, smtplib, importlib
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone

GREEN  = "\033[92m"; YELLOW = "\033[93m"; RED    = "\033[91m"
CYAN   = "\033[96m"; DIM    = "\033[2m";  BOLD   = "\033[1m"; RESET  = "\033[0m"

def ok(msg):   print(f"  {GREEN}OK{RESET}  {msg}")
def warn(msg): print(f"  {YELLOW}WN{RESET}  {msg}")
def fail(msg): print(f"  {RED}XX{RESET}  {msg}")
def info(msg): print(f"  {CYAN}->{RESET}  {msg}")
def head(msg): print(f"\n{BOLD}{msg}{RESET}")

issues = []
PIPELINE_DIR = Path(r"C:\Users\Mike\Desktop\Earthquake Feed Listener Engine")
REPO_DIR     = Path(r"C:\Users\Mike\Desktop\repo")

# â”€â”€ Load .env â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
env_lines = {}
env_path = PIPELINE_DIR / ".env"
if env_path.exists():
    raw = env_path.read_bytes()
    content = raw[3:].decode("utf-8") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("utf-8")
    env_lines = {l.split("=")[0].strip(): l.split("=",1)[1].strip()
                 for l in content.splitlines() if "=" in l and not l.strip().startswith("#")}

# â”€â”€ 1. Required files â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 1 ] Required files")
REQUIRED = [
    "pipeline.py","usgs_listener.py","rinex_downloader.py","detector_runner.py",
    "scorer.py","dart_checker.py","space_weather.py","ionosonde_checker.py",
    "notify.py","notify_discord.py","backtest.py","adaptive_thresholds.py",
    "health_check.py","run_and_push.bat",
]
for f in REQUIRED:
    p = PIPELINE_DIR / f
    if p.exists(): ok(f)
    else: fail(f"{f} -- MISSING"); issues.append(f"Missing: {f}")

# â”€â”€ 2. Credentials (.env) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 2 ] Credentials (.env)")
if not env_path.exists():
    fail(".env not found"); issues.append("No .env file")
else:
    for key, label in [
        ("EARTHDATA_USER","EARTHDATA_USER"),("EARTHDATA_PASS","EARTHDATA_PASS"),
        ("NOTIFY_EMAIL","NOTIFY_EMAIL"),("NOTIFY_APP_PASSWORD","NOTIFY_APP_PASSWORD"),
        ("DISCORD_WEBHOOK_URL","DISCORD_WEBHOOK_URL"),
    ]:
        val = env_lines.get(key,"")
        if val:
            display = val if key in ("EARTHDATA_USER","NOTIFY_EMAIL") else "*"*min(len(val),16)
            ok(f"{label} = {display}")
        else:
            if key in ("NOTIFY_APP_PASSWORD",):
                warn(f"{label} not set -- email alerts disabled")
            else:
                fail(f"{label} not set"); issues.append(f"Missing {label}")
    webhook = env_lines.get("DISCORD_WEBHOOK_URL","")
    if webhook and "discord.com/api/webhooks/" not in webhook:
        fail("DISCORD_WEBHOOK_URL malformed"); issues.append("Malformed webhook URL")
    bad = [l for l in content.splitlines() if "Out-File" in l or "Add-Content" in l]
    if bad: fail(".env contains PowerShell commands -- recreate it"); issues.append(".env corrupted")

# â”€â”€ 3. Python module imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 3 ] Python module imports")
MODULES = ["numpy","scipy","pandas","matplotlib","georinex","ncompress","requests",
           "dart_checker","space_weather","ionosonde_checker","notify","notify_discord"]
os.chdir(PIPELINE_DIR)
for mod in MODULES:
    try:
        importlib.import_module(mod)
        ok(mod)
    except ImportError as e:
        fail(f"{mod} -- {e}"); issues.append(f"Import failed: {mod}")

# â”€â”€ 4. Pipeline module integrity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 4 ] Pipeline module integrity")
try:
    import notify_discord as nd
    has_detection = hasattr(nd, "send_detection_alert")
    has_error     = hasattr(nd, "send_pipeline_error")
    ok("notify_discord.send_detection_alert") if has_detection else (fail("notify_discord missing send_detection_alert"), issues.append("notify_discord.send_detection_alert missing"))
    ok("notify_discord.send_pipeline_error")  if has_error     else (fail("notify_discord missing send_pipeline_error"),  issues.append("notify_discord.send_pipeline_error missing"))
except Exception as e:
    fail(f"notify_discord check failed: {e}"); issues.append("notify_discord integrity check failed")

try:
    import space_weather as sw
    has_fetch = hasattr(sw, "get_space_weather_quality")
    ok("space_weather module loaded") if has_fetch else warn("space_weather loaded but expected functions not found")
except Exception as e:
    fail(f"space_weather check failed: {e}"); issues.append("space_weather integrity check failed")

try:
    import dart_checker as dc
    buoy_count = len(getattr(dc, "DART_BUOYS", []))
    ok(f"dart_checker loaded -- {buoy_count} buoys configured")
except Exception as e:
    fail(f"dart_checker check failed: {e}"); issues.append("dart_checker integrity check failed")

try:
    import ionosonde_checker as ic
    sta_count = len(getattr(ic, "IONOSONDE_STATIONS", {}))
    ok(f"ionosonde_checker loaded -- {sta_count} stations configured")
except Exception as e:
    fail(f"ionosonde_checker check failed: {e}"); issues.append("ionosonde_checker integrity check failed")

# â”€â”€ 5. Pipeline dedup check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 5 ] Pipeline dedup check")
pl = (PIPELINE_DIR / "pipeline.py").read_text(encoding="utf-8")
nd_imports = pl.count("import notify_discord\n")
da_blocks  = pl.count("discord_alerted")
err_calls  = pl.count("send_pipeline_error")
ok(f"notify_discord imported once ({nd_imports})") if nd_imports == 1 else (fail(f"notify_discord imported {nd_imports}x -- duplicate"), issues.append("Duplicate notify_discord import"))
ok(f"discord_alerted blocks: {da_blocks} (expected 2)") if da_blocks == 2 else warn(f"discord_alerted count={da_blocks} unexpected")
ok(f"send_pipeline_error called once ({err_calls})") if err_calls == 1 else (fail(f"send_pipeline_error called {err_calls}x -- duplicate"), issues.append("Duplicate send_pipeline_error"))

# â”€â”€ 6. USGS feed â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 6 ] USGS Earthquake Feed")
try:
    req = urllib.request.Request(
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson",
        headers={"User-Agent":"gps-tsunami-health-check"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
        ok(f"USGS feed reachable -- {len(data.get('features',[]))} events this week")
except Exception as e:
    fail(f"USGS feed: {e}"); issues.append("USGS feed unreachable")

# â”€â”€ 7. NASA CDDIS auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 7 ] NASA CDDIS Auth (real credential test)")
user = env_lines.get("EARTHDATA_USER","")
pwd  = env_lines.get("EARTHDATA_PASS","")
if not user or not pwd:
    warn("Skipping CDDIS auth test -- credentials missing")
else:
    try:
        import requests as req_lib
        class _EDS(req_lib.Session):
            def rebuild_auth(self, prep, resp):
                if self.auth: prep.prepare_auth(self.auth, prep.url)
        s = _EDS(); s.auth = (user, pwd)
        today = datetime.now(timezone.utc)
        yr2 = str(today.year)[-2:]
        doy = today.timetuple().tm_yday
        test_url = f"https://cddis.nasa.gov/archive/gps/data/daily/{today.year}/{doy:03d}/{yr2}o/"
        r = s.get(test_url, timeout=12)
        if r.status_code == 200 and "text/html" not in r.headers.get("Content-Type",""):
            ok(f"CDDIS auth OK -- {r.status_code}")
        elif r.status_code == 200:
            ok(f"CDDIS auth OK -- directory listing ({r.status_code})")
        elif r.status_code in [401,403]:
            fail(f"CDDIS auth FAILED ({r.status_code}) -- check EARTHDATA credentials")
            issues.append("CDDIS auth failed -- bad credentials")
        else:
            warn(f"CDDIS returned {r.status_code}")
    except Exception as e:
        warn(f"CDDIS auth test error: {e}")

# â”€â”€ 8. NOAA SWPC space weather â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 8 ] NOAA SWPC Space Weather Feeds")
SWPC = [
    ("Kp index",  "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"),
    ("Solar wind","https://services.swpc.noaa.gov/products/solar-wind/plasma-7-day.json"),
    ("IMF Bz",    "https://services.swpc.noaa.gov/products/solar-wind/mag-7-day.json"),
    ("GOES X-ray","https://services.swpc.noaa.gov/json/goes/primary/xrays-7-day.json"),
]
for name, url in SWPC:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"gps-tsunami-health-check"}), timeout=10) as r:
            d = json.loads(r.read())
            ok(f"SWPC {name} -- {len(d)} records")
    except Exception as e:
        fail(f"SWPC {name}: {e}"); issues.append(f"SWPC {name} unreachable")

# â”€â”€ 9. NOAA NDBC DART buoys â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 9 ] NOAA NDBC / DART Buoy API")
for buoy_id, label in [("51407","Hawaii"),("46409","Aleutian"),("55012","Tonga")]:
    try:
        url = f"https://www.ndbc.noaa.gov/data/realtime2/{buoy_id}.dart"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"gps-tsunami-health-check"}), timeout=10) as r:
            lines = [l for l in r.read().decode("utf-8",errors="ignore").splitlines()
                     if l.strip() and not l.startswith("#") and not l.startswith("Y")]
            ok(f"DART {buoy_id} ({label}) -- {len(lines)} records")
    except urllib.error.HTTPError as e:
        warn(f"DART {buoy_id} ({label}) -- HTTP {e.code} (buoy may be offline)")
    except Exception as e:
        fail(f"DART {buoy_id}: {e}"); issues.append(f"NDBC API unreachable (buoy {buoy_id})")

# â”€â”€ 10. GIRO ionosonde API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 10 ] GIRO Digisonde API")
giro_ok = 0
for sid, label in [("GU513","Guam"),("WP937","Wake Island"),("KJ609","Kwajalein")]:
    try:
        url = (f"https://lgdc.uml.edu/common/DIDBGetValues?ursiCode={sid}"
               f"&charName=foF2&DMUF=3000&fromDate=2024-01-01+00%3A00%3A00"
               f"&toDate=2024-01-01+06%3A00%3A00&fmt=JSONf")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"gps-tsunami-health-check"}), timeout=12) as r:
            raw = r.read().decode("utf-8",errors="ignore")
            ok(f"GIRO {sid} ({label}) -- responding ({len(raw)} bytes)")
            giro_ok += 1
    except Exception as e:
        warn(f"GIRO {sid}: {e}")
if giro_ok == 0:
    fail("No GIRO stations responding"); issues.append("GIRO API unreachable")

# â”€â”€ 11. NOAA tide gauge (scoring endpoint) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 11 ] NOAA Tide Gauge (scoring endpoint)")
try:
    url = ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
           "?product=water_level&application=gps-tsunami-health-check"
           "&begin_date=20240101&end_date=20240101"
           "&datum=MLLW&station=1617760&time_zone=GMT&units=metric&interval=h&format=json")
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
        if "data" in data:
            ok(f"NOAA CO-OPS API -- Hilo gauge responding ({len(data['data'])} records)")
        else:
            warn(f"NOAA response: {data.get('error','?')}")
except Exception as e:
    fail(f"NOAA tide gauge: {e}"); issues.append("NOAA tide gauge API unreachable")

# â”€â”€ 12. Gmail SMTP connectivity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 12 ] Gmail SMTP (email alerts)")
email = env_lines.get("NOTIFY_EMAIL","")
apwd  = env_lines.get("NOTIFY_APP_PASSWORD","")
if not email or not apwd:
    warn("NOTIFY_EMAIL or NOTIFY_APP_PASSWORD not set -- skipping SMTP test")
else:
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as srv:
            srv.login(email, apwd)
            ok(f"Gmail SMTP auth OK -- {email}")
    except smtplib.SMTPAuthenticationError:
        fail("Gmail SMTP auth FAILED -- check NOTIFY_APP_PASSWORD")
        issues.append("Gmail SMTP auth failed")
    except Exception as e:
        warn(f"Gmail SMTP test error: {e}")

# â”€â”€ 13. Discord webhook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 13 ] Discord Webhook")
webhook = env_lines.get("DISCORD_WEBHOOK_URL","")
if not webhook:
    fail("DISCORD_WEBHOOK_URL not set"); issues.append("Discord webhook not configured")
elif "discord.com/api/webhooks/" not in webhook:
    fail("DISCORD_WEBHOOK_URL malformed"); issues.append("Malformed webhook URL")
else:
    try:
        with urllib.request.urlopen(urllib.request.Request(webhook, headers={"User-Agent":"gps-tsunami-health-check"}), timeout=10) as r:
            data = json.loads(r.read())
            ok(f"Discord webhook valid -- channel: '{data.get('name','?')}'")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            fail("Discord webhook 401 -- URL invalid or deleted, regenerate it")
            issues.append("Discord webhook invalid")
        else:
            warn(f"Discord webhook HTTP {e.code}")
    except Exception as e:
        warn(f"Discord webhook error: {e}")

# â”€â”€ 14. GitHub repo + dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 14 ] GitHub Repository & Dashboard")
BASE = "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/"
for fname, label in [("running_log.json","running_log"),("poll_log.json","poll_log")]:
    try:
        with urllib.request.urlopen(BASE+fname, timeout=10) as r:
            data = json.loads(r.read())
            if fname == "poll_log.json":
                ok(f"{label} accessible -- {data.get('total_polls',0)} polls")
            else:
                ok(f"{label} accessible -- {len(data.get('scored_events',[]))} scored events")
    except Exception as e:
        fail(f"{label}: {e}"); issues.append(f"{label} not accessible on GitHub")
try:
    with urllib.request.urlopen("https://beastros.github.io/gps-tsunami-detection/", timeout=10) as r:
        html = r.read().decode("utf-8",errors="ignore")
        ok("Dashboard live") if "GPS Tsunami" in html else warn("Dashboard reachable but content unexpected")
except Exception as e:
    fail(f"Dashboard: {e}"); issues.append("Dashboard not loading")

# â”€â”€ 15. Git repo health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 15 ] Git Repo / Push Health")
if REPO_DIR.exists():
    ok("Repo folder found")
    try:
        log_r = subprocess.run(["git","-C",str(REPO_DIR),"log","--oneline","-1"], capture_output=True, text=True, timeout=10)
        if log_r.returncode == 0: ok(f"Last commit: {log_r.stdout.strip()}")
        stat = subprocess.run(["git","-C",str(REPO_DIR),"status","--short"], capture_output=True, text=True, timeout=10)
        if stat.stdout.strip(): warn("Uncommitted changes in repo"); issues.append("Repo has uncommitted changes")
        else: ok("Repo working tree clean")
        rem = subprocess.run(["git","-C",str(REPO_DIR),"ls-remote","--heads","origin"], capture_output=True, text=True, timeout=15)
        ok("GitHub remote reachable") if rem.returncode == 0 else (fail("GitHub remote unreachable"), issues.append("Git remote unreachable"))
    except Exception as e:
        warn(f"Git check error: {e}")
else:
    fail(f"Repo folder not found"); issues.append("Repo folder missing")

# â”€â”€ 16. Station network integrity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 16 ] GPS Station Network (V4)")
det = (PIPELINE_DIR / "detector_runner.py").read_text(encoding="utf-8") if (PIPELINE_DIR / "detector_runner.py").exists() else ""
rin = (PIPELINE_DIR / "rinex_downloader.py").read_text(encoding="utf-8") if (PIPELINE_DIR / "rinex_downloader.py").exists() else ""
for sid in ["mkea","kokb","hnlc","guam","chat","thti","thtg","auck","noum","kwj1","holb"]:
    if f'"{sid}"' in det: ok(f"{sid.upper()} in detector_runner.py")
    else: fail(f"{sid.upper()} MISSING from detector_runner.py"); issues.append(f"Missing station: {sid.upper()}")
for sid in ["auck","noum","kwj1","holb"]:
    if f'"{sid}"' in rin: ok(f"{sid.upper()} in CORRIDOR_STATIONS")
    else: fail(f"{sid.upper()} MISSING from rinex_downloader.py"); issues.append(f"Missing corridor: {sid.upper()}")

# â”€â”€ 17. Log files freshness â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 17 ] Log File Freshness")
for lf in ["poll_log.json","task_runner.log"]:
    p = PIPELINE_DIR / lf
    if not p.exists():
        warn(f"{lf} not found locally")
        continue
    age_min = (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 60
    if lf in ("task_runner.log", "poll_log.json"):
        if age_min < 20:   ok(f"{lf} -- last written {age_min:.0f} min ago")
        elif age_min < 60: warn(f"{lf} -- {age_min:.0f} min ago (missed a cycle?)"); issues.append(f"{lf} stale")
        else:              fail(f"{lf} -- {age_min:.0f} min ago (pipeline may be down)"); issues.append("Pipeline log stale")
    else:
        if age_min < 20:   ok(f"{lf} -- updated {age_min:.0f} min ago")
        elif age_min < 60: warn(f"{lf} -- {age_min:.0f} min ago")
        else:              fail(f"{lf} -- {age_min:.0f} min ago"); issues.append(f"{lf} stale")

# â”€â”€ 18. Event queue â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 18 ] Event Queue")
qf = PIPELINE_DIR / "event_queue.json"
if qf.exists():
    try:
        q = json.loads(qf.read_text())
        events = q.get("events",[]); seen = len(q.get("seen_ids",[]))
        pending = [e for e in events if e.get("status") not in ["scored"]]
        scored  = [e for e in events if e.get("status") == "scored"]
        ok(f"event_queue.json -- {seen} USGS IDs seen, {len(events)} events ({len(pending)} pending, {len(scored)} scored)")
        for e in pending[:3]: info(f"  Mw{e.get('magnitude','?')} {e.get('place','?')[:40]} status={e.get('status','?')}")
    except Exception as e:
        warn(f"event_queue.json parse error: {e}")
else:
    warn("event_queue.json not found"); issues.append("No event queue")

# â”€â”€ 19. Adaptive thresholds â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 19 ] Adaptive Thresholds")
rf = PIPELINE_DIR / "threshold_recommendations.json"
if rf.exists():
    try:
        recs = json.loads(rf.read_text(encoding="utf-8"))
        n_tp = recs.get("n_tp_total",0); run = recs.get("run_utc","?")[:16]
        ok(f"threshold_recommendations.json -- {n_tp} TP obs, last run {run}")
        if n_tp < 10: info(f"Only {n_tp} TP obs -- recommendations advisory, do not apply yet")
    except Exception as e:
        warn(f"threshold_recommendations.json parse error: {e}")
else:
    warn("threshold_recommendations.json not found -- run adaptive_thresholds.py"); issues.append("Run adaptive_thresholds.py")

# â”€â”€ 20. Task Scheduler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
head("[ 20 ] Windows Task Scheduler")
bat = PIPELINE_DIR / "run_and_push.bat"
ok("run_and_push.bat found") if bat.exists() else (fail("run_and_push.bat missing"), issues.append("run_and_push.bat missing"))
try:
    r = subprocess.run(["schtasks","/query","/tn","GPS Tsunami Master","/fo","LIST"], capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        lines = r.stdout.strip().splitlines()
        status   = next((l.split(":",1)[1].strip() for l in lines if "Status"   in l),"?")
        next_run = next((l.split(":",1)[1].strip() for l in lines if "Next Run" in l),"?")
        last_run = next((l.split(":",1)[1].strip() for l in lines if "Last Run" in l),"?")
        if status.lower() in ["ready","running"]:
            ok(f"Task 'GPS Tsunami Master': {status}")
            ok(f"Last: {last_run}  |  Next: {next_run}")
        else:
            warn(f"Task status: {status}"); issues.append(f"Scheduler status: {status}")
    else:
        fail("Task not found in Task Scheduler"); issues.append("Task Scheduler not configured")
except Exception as e:
    warn(f"Task Scheduler check error: {e}")


# === Section 22: DYFI Checker ===
print("\n--- Section 22: DYFI Checker ---")
_dyfi_ok = False
try:
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "dyfi_checker",
        os.path.join(PIPELINE_DIR, "dyfi_checker.py"),
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    ok("dyfi_checker.py loaded OK")
    _dyfi_ok = True
except Exception as _e:
    fail("dyfi_checker.py import failed: " + str(_e))
    issues.append("dyfi_checker.py import failed")

if _dyfi_ok:
    try:
        _contrib, _resp, _mmi, _conf = _mod.get_dyfi_contribution("us7000n7n8")
        if _resp is not None:
            ok("DYFI API reachable -- responses=%d maxmmi=%s contrib=%.2f" % (_resp, _mmi, _contrib))
        else:
            warn("DYFI API returned no data for test event (may be expired) -- fail-open OK")
    except Exception as _e:
        warn("DYFI API test: " + str(_e) + " -- fail-open OK")


# === Section 23: DYFI Poller ===
print("\n--- Section 23: DYFI Poller ---")
_poller_path = os.path.join(PIPELINE_DIR, "dyfi_poller.py")
_pings_path  = r"C:\Users\Mike\Desktop\repo\dyfi_pings.json"
if os.path.exists(_poller_path):
    ok("dyfi_poller.py found")
else:
    fail("dyfi_poller.py missing from pipeline folder")
    issues.append("dyfi_poller.py missing")
import time as _t23, json as _j23
if os.path.exists(_pings_path):
    _age = _t23.time() - os.path.getmtime(_pings_path)
    try:
        _pd = _j23.load(open(_pings_path, encoding="utf-8"))
        if _age < 1800:
            ok("dyfi_pings.json fresh -- %d pings" % _pd.get("count", 0))
        else:
            warn("dyfi_pings.json %d min old -- updates next cycle" % int(_age/60))
    except Exception as _e:
        warn("dyfi_pings.json parse error: " + str(_e))
else:
    warn("dyfi_pings.json not yet written -- appears after first pipeline cycle")
# â”€â”€ Summary â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print(f"\n{'='*55}")
if not issues:
    print(f"{GREEN}{BOLD}  ALL SYSTEMS OPERATIONAL{RESET}")
    print(f"{DIM}  Pipeline healthy. Monitoring Pacific basin.{RESET}")
else:
    print(f"{YELLOW}{BOLD}  {len(issues)} ISSUE(S) FOUND:{RESET}")
    for i, issue in enumerate(issues,1):
        print(f"  {RED}{i}.{RESET} {issue}")
print(f"{'='*55}\n")




