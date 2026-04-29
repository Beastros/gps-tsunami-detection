# Claude Code Rules — GPS Tsunami Detection Project
## Lessons Learned, Syntax Rules, and Environment Reference
### Last updated: 2026-04-28 | Version: V6 session

---

## CRITICAL DEPLOYMENT RULES

### 1. Never use deploy scripts with `.py` extensions that contain dots in the base name
The claude.ai chat UI converts any word matching a real domain (discord.py, notify.py, path.py, backtest.py, etc.) into a hyperlink when rendered. When Mike copy-pastes commands, the filename becomes `[discord.py](http://discord.py)` and Python can't find it.

**Safe filenames:** `setup_discord.py`, `fix_notify.py`, `fix_path.py`, `update_readme.py`
**Unsafe filenames:** anything where the base name before `.py` is a real domain or common word

### 2. Always use PowerShell here-strings for patching files in place
Never use multi-line `python -c "..."` with nested quotes — PowerShell mangles them.
Use this pattern instead:

```powershell
@'
p = r"C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\target.py"
s = open(p, encoding="utf-8").read()
s = s.replace("old text", "new text")
open(p, "w", encoding="utf-8").write(s)
print("patched OK")
'@ | Out-File -FilePath patch_something.py -Encoding utf8
python patch_something.py
```

### 3. Deploy scripts must self-delete old Downloads copies
Always include cleanup at the top of every deploy script:

```python
import os
DOWNLOADS = os.path.join(os.environ["USERPROFILE"], "Downloads")
for f in ["target.py", "target (1).py", "target (2).py"]:
    p = os.path.join(DOWNLOADS, f)
    if os.path.exists(p): os.remove(p)
```

### 4. Browser download cache creates numbered duplicates
When Mike downloads a file multiple times, Chrome saves them as `file.py`, `file (1).py`, `file (2).py`. The old version is always run unless explicitly deleted first. Always tell Mike to run the highest-numbered copy, or better, use self-deleting deploy scripts.

### 5. Never use triple-quoted strings inside deploy scripts
Embedding file content as triple-quoted strings inside deploy scripts causes syntax errors when the content contains quotes. Use base64 encoding instead:

```python
import base64, os
DATA = "base64encodedcontenthere"
out = os.path.join(PIPELINE_DIR, "target.py")
with open(out, "wb") as f:
    f.write(base64.b64decode(DATA))
```

Always verify the embedded content before presenting:
```python
import ast, base64
ast.parse(base64.b64decode(DATA).decode('utf-8'))
print("Syntax OK")
```

### 6. Always open files with encoding="utf-8"
Windows defaults to cp1252 which can't handle Unicode characters (arrows →, checkmarks ✓, em-dashes —). Every file read/write must specify encoding:

```python
open(path, "r", encoding="utf-8")
open(path, "w", encoding="utf-8")
```

### 7. Notepad saves files with BOM (Byte Order Mark)
When Mike edits `.env` or any file in Notepad, it adds an invisible `\xef\xbb\xbf` at the start. This breaks python-dotenv. Always strip BOM when reading .env manually:

```python
raw = open(".env", "rb").read().lstrip(b"\xef\xbb\xbf").decode("utf-8")
```

### 8. Never use python-dotenv for .env loading in this project
The .env file has comments and blank lines that trigger dotenv parse warnings. Load it manually:

```python
def load_env(path=".env"):
    try:
        raw = open(path, "rb").read().lstrip(b"\xef\xbb\xbf").decode("utf-8")
        for line in raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass
```

### 9. Unicode characters in log messages crash on Windows cp1252
Detector_runner.py uses Unicode arrows and checkmarks in log.info() calls. These crash the StreamHandler on Windows with UnicodeEncodeError. The bare `except: continue` in the station loop silently catches this and skips the station, making it look like no RINEX was found.

Fix: always open log FileHandlers with `encoding="utf-8"` AND replace Unicode chars with ASCII in log strings.

### 10. NASA CDDIS requires Earthdata session auth, not basic auth
`requests.get(url, auth=(user, pass))` does NOT work with CDDIS. The server redirects to `urs.earthdata.nasa.gov`, requests follows the redirect but doesn't re-send credentials, and gets back a 200 HTML login page. The HTML gets saved as the .Z file.

Fix — use a custom session class in rinex_downloader.py:
```python
class _EarthdataSession(requests.Session):
    def rebuild_auth(self, prepared_request, response):
        if self.auth:
            prepared_request.prepare_auth(self.auth, prepared_request.url)
```

Also add HTML content detection before saving:
```python
if "text/html" in r.headers.get("Content-Type", ""):
    return False  # auth failed
```

### 11. decompress() returns None silently when ncompress fails
If a .Z file is actually HTML (corrupt download), ncompress raises `ValueError: not in LZW-compressed format` which decompress() catches and returns None. The station loop skips it silently. Always check file magic bytes before trusting it:

```python
raw = open(path, "rb").read(4)
if raw[:1] == b"<":
    # HTML error page, not real data
```

### 12. PowerShell does not support && for chaining commands
Run git commands on separate lines. Never chain with &&.

### 13. dir command in PowerShell doesn't support /s /b flags
Use `Get-ChildItem -Path folder -Recurse -Filter "*.ext"` instead of `dir folder /s /b`.

### 14. Never use `copy /Y` in PowerShell — use Copy-Item
`copy /Y` is CMD syntax and fails in PowerShell with parameter binding errors.

**Never:**
```powershell
copy /Y "C:\source\file.py" "C:\dest\file.py"
```

**Always:**
```powershell
Copy-Item "C:\source\file.py" "C:\dest\file.py" -Force
```

---

## PATHS AND DIRECTORIES

### Pipeline folder (where scripts run)
```
C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\
```
This is where all Python scripts live and run from. Task Scheduler runs pipeline.py from here.

### Repo folder (git)
```
C:\Users\Mike\Desktop\repo\
```
GitHub: github.com/Beastros/gps-tsunami-detection (branch: main)
Dashboard: beastros.github.io/gps-tsunami-detection/

### Downloads folder
```
C:\Users\Mike\Downloads\
```
Reference as: `os.path.join(os.environ["USERPROFILE"], "Downloads")`

### RINEX data location
```
C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\rinex_live\<usgs_id>\
```
Files follow pattern: `{station}{doy:03d}0.{yr2}o.Z` and `{station}{doy:03d}0.{yr2}n.Z`

---

## ENVIRONMENT VARIABLES (.env file)

Location: `C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\.env`

```
EARTHDATA_USER=mthhorn
EARTHDATA_PASS=<NASA Earthdata password>
NOTIFY_EMAIL=mthhorn@gmail.com
NOTIFY_APP_PASSWORD=<Gmail app password>
DISCORD_WEBHOOK_URL=<regenerate at Discord after each session — was exposed in chat>
```

**Important:** The Discord webhook URL from the April 26 2026 session was exposed in chat and should have been regenerated. Always regenerate after any session where it appears in chat logs.

---

## PIPELINE ARCHITECTURE

### File locations (Pipeline folder vs Repo)
Files in Pipeline folder only (not committed to GitHub):
- pipeline.py, rinex_downloader.py, dart_checker.py, notify.py, health_check.py, run_and_push.bat

Files in both Pipeline folder AND repo:
- detector_runner.py, usgs_listener.py, scorer.py, space_weather.py, ionosonde_checker.py
- notify_discord.py (added V3)
- backtest.py (added V3)
- index.html, poll_log.json, running_log.json, event_queue.json

### Task Scheduler
Task name: 'GPS Tsunami Master'
Runs: every 15 min as SYSTEM
Target: run_and_push.bat

### Fast Poll Mode (added V6)
When any Mw>=6.0 Pacific zone event is detected, usgs_listener.py writes fast_poll.json
with a 2-hour expiry. pipeline.py --once checks this file after each cycle — if active
and not expired, sleeps 2 min and runs again internally (~6-7 cycles per 15-min window).
Trigger is lower than 6.5 qualify threshold to catch USGS magnitude upgrades early.
fast_poll.json location: pipeline folder (not committed to GitHub).

### Deploy pattern
ALWAYS bake files as base64 in deploy scripts to avoid download cache issues.
ALWAYS delete old Downloads copies at start of deploy script.
NEVER reuse old deploy scripts from Downloads.

---

## KEY TECHNICAL FACTS

### RINEX file format
- Extension `.Z` = Unix LZW compress format (magic bytes: `1f 9d`)
- NASA CDDIS serves real LZW files when auth works correctly
- HTML error pages have magic bytes starting with `3c 21` (`<!`)
- Decompressed files have no extension: `mkea0700.11o`
- decompress() in detector_runner.py: if decompressed file exists, returns it without re-checking validity

### Station network (V5 — 10 stations + zone constraints)
MKEA: Mauna Kea HI (19.801, -155.456, 3763m) — no zone constraint
KOKB: Kokee Kauai HI (22.127, -159.665, 1167m) — no zone constraint
HNLC: Honolulu HI (21.297, -157.816, 5m) — no zone constraint
GUAM: Guam (13.489, 144.868, 83m) — no zone constraint
CHAT: Chatham Islands NZ (-43.956, -176.566, 63m) — no zone constraint
THTI/THTG: Tahiti (-17.577, -149.606, 87m) — no zone constraint
AUCK: Auckland NZ (-36.602, 174.834, 106m) — no zone constraint
NOUM: Noumea NC (-22.270, 166.413, 69m) — no zone constraint
KWJ1: Kwajalein Marshall Islands (8.722, 167.730, 39m) — no zone constraint
HOLB: Holberg BC Canada (50.640, -128.133, 180m) — Cascadia only: lat 40-52, lon -135 to -120

### Confidence formula (from detector_runner.py)
```
tec_reliability = max(1.0 - sw_score * 0.6, 0.2)
tec_contrib = 0.55 * tec_reliability * tsunamigenic_weight  (0 if not detected)
dart_contrib = dart_score * 0.45  (-0.08 if negative)
const_contrib = +0.10 agreement / -0.10 disagreement / +0.03 partial
dtec_contrib = 0.05 if dtec_corroborates
iono_contrib = 0.12 if ionosonde_confirmed
combined = min(sum of above, 1.0)
```

### Backtest results (V5 — April 26 2026)
9 events: TP=4, TN=5, FP=0, FN=0
TPR=1.00, FPR=0.00
Note: DART/ionosonde historical data unavailable via API — all confidence scores are GPS-TEC only (0.52)

---

## KNOWN ISSUES AND WORKAROUNDS

### GIRO ionosonde historical data
GIRO DIDBase API doesn't return data for pre-2024 events at most stations.
ionosonde_checker.py has fail-open: no data = ionosonde_confirmed=False, no penalty.

### DART historical data
NDBC DART API only returns recent data. Historical tsunami signals from 2006-2013 events are not available. All backtest confidence scores are TEC-only as a result.

### detector_runner.py bare except in station loop
The station processing loop has `except: continue` which silently swallows ALL exceptions including UnicodeEncodeError from log statements. Any Unicode in log.info() calls will cause stations to be skipped. All log strings must use ASCII only.

### rinex_downloader.py corridor station routing
download_event() uses event["primary_anchor"] to select stations via CORRIDOR_STATIONS dict. If primary_anchor is None or missing, falls back to CORRIDOR_STATIONS[None]. The backtest must set primary_anchor correctly or stations won't match the event geography.

### Sumatra 2012 strike-slip result
Expected: ShakeMap gate. Actual: TEC coherence test failed (no coherent pairs found). Result is still TRUE_NEGATIVE but for different reason than expected. In live pipeline, ShakeMap gate fires first and event never reaches detector.

### Okhotsk 2013 deep event
Expected: depth gate in usgs_listener.py (>100km). Actual in backtest: bypasses listener, reaches detector, gets FALSE_POSITIVE at conf=0.52. In live pipeline, depth gate fires first. Document this in paper as testing artifact.

### pipeline.py has a BOM — always open with utf-8-sig
pipeline.py was edited in Notepad at some point and has a UTF-8 BOM at the start.
Any script that reads pipeline.py for patching MUST use utf-8-sig encoding or ast.parse() will fail with "invalid non-printable character U+FEFF".

```python
# WRONG:
src = open(pl_path, encoding="utf-8").read()

# CORRECT:
src = open(pl_path, encoding="utf-8-sig").read()  # strips BOM if present
```

### Do not use web search for same-day seismic events
For verifying whether a qualifying earthquake occurred, query the USGS API directly —
never use web search or Wikipedia for breaking seismic news. Wikipedia same-day articles
are unreliable. The authoritative source is the USGS feed itself:

```python
import requests
r = requests.get(
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    "?format=geojson&starttime=2026-04-24&minmagnitude=6.5&orderby=time"
).json()
for f in r["features"]:
    print(f["properties"]["mag"], f["properties"]["place"], f["geometry"]["coordinates"][2])
```

---

## WORKFLOW RULES

### 15. Never put .py filenames inside quoted strings in PowerShell commands
The claude.ai chat UI converts any word matching a real domain (pipeline.py, health_check.py, notify.py etc.) into a hyperlink when rendered. When Mike copy-pastes commands, the filename becomes `[pipeline.py](http://pipeline.py)` and PowerShell/Python can't find the file.

**Never do this:**
```powershell
Get-Content "C:\path\pipeline.py"
python patch_something.py
$f = "health_check.py"
```

**Always do this instead:**
```powershell
Get-Content (Get-ChildItem "C:\path" -Filter "pipeline*")
$f = (Get-ChildItem . -Filter "health_check*").FullName; python $f
```

### 16. Always cd into the target directory before running wildcard Get-ChildItem
Get-ChildItem returns full paths but Get-Content resolves relative to the current directory.

**Pattern:**
```powershell
cd "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine"
$f = (Get-ChildItem . -Filter "pipeline*" | Where-Object {$_.Name -notlike "*.log"}).FullName
$p = Get-Content $f -Raw
```

### 17. Use semicolons to chain PowerShell commands into one paste
```powershell
cd "C:\path"; $p = Get-Content $f -Raw; ($p | Select-String "pattern").Matches.Count
```

### 18. Use PowerShell -replace for small patches instead of Python scripts
For changes under ~10 lines, PowerShell regex replace is faster than a Python download-copy-run cycle:

```powershell
$f = (Get-ChildItem "C:\Users\Mike\Desktop\repo" -Filter "health_check*").FullName
$p = Get-Content $f -Raw
$p = $p -replace 'old string', 'new string'
Set-Content $f $p -Encoding UTF8
```

### 19. task_runner.log is the live pipeline log, not pipeline.log
pipeline.log, runner.log, scorer.log are only written when scripts are run manually.
task_runner.log is written by run_and_push.bat every 15-minute Task Scheduler cycle.
Health checks and freshness monitoring should watch task_runner.log.

### 20. running_log.json only updates on scored events -- do not flag as stale
running_log.json is updated by scorer.py when a prediction is scored against tide gauges.
With 0 qualifying live events, it will be perpetually "stale" by mtime.
Health checks should not treat this as an error condition.

### 21. Never use Set-Content or Out-File to write files containing non-ASCII
PowerShell's `Set-Content -Encoding utf8` and `Out-File -Encoding utf8` both add a BOM
and/or mangle emoji and Unicode symbols. Any file that contains non-ASCII (index.html,
any .md with arrows or emoji) MUST be written with Python or with .NET directly.

**Never:**
```powershell
Set-Content $f $content -Encoding utf8
$content | Out-File $f -Encoding utf8
```

**Always use Python for file writes:**
```python
open(path, "w", encoding="utf-8", newline="\n").write(content)
```

### 22. Pair names in detector_runner.py window_pairs are LOWERCASE
The `window_pairs` list stores pair dicts where `p['pair']` is a lowercase hyphenated
string e.g. `'kokb-guam'`, `'guam-holb'`. Any dict keyed on station names must use `.upper()` when doing lookups:

```python
if stn.upper() in STATION_ZONE_CONSTRAINTS:
    z = STATION_ZONE_CONSTRAINTS[stn.upper()]
```

### 23. Always patch index.html with Python, never PowerShell
index.html contains emoji and Unicode symbols. Any PowerShell write will double-encode
these into mojibake. All index.html modifications must go through Python with:
```python
src = open(f, encoding='utf-8').read()
open(f, 'w', encoding='utf-8', newline='\n').write(src)
```

### 24. Fix mojibake with raw byte replacement, not Unicode escape strings
When fixing double-encoded UTF-8 (mojibake), always use raw bytes:
```python
raw = open(f, 'rb').read()
raw = raw.replace(b'\xc3\xb0\xc5\xb8\xc5\x92\xc5\xa0', '\U0001f30a'.encode('utf-8'))
open(f, 'wb').write(raw)
```

### 25. Always verify health_check.py patches applied before committing
After patching health_check.py, confirm the section was actually inserted:
```powershell
$f = (Get-ChildItem "C:\Users\Mike\Desktop\repo" -Filter "health_check*" | Where-Object {$_.Extension -eq ".py"}).FullName
$p = [System.IO.File]::ReadAllText($f, [System.Text.Encoding]::UTF8)
$p.Contains("Zone Constraint Integrity")
```

### 26. Delete stray patch files from repo before final commit each session
```powershell
Remove-Item "C:\Users\Mike\Desktop\repo\patch_*.py"
```

### 27. pipeline.py has a BOM — always open with utf-8-sig
See "Known Issues" section above. This applies to any patch script that reads pipeline.py.

### 28. Copy files between pipeline folder and repo using Copy-Item, not copy /Y
`copy /Y` is CMD syntax. In PowerShell always use:
```powershell
Copy-Item "C:\Users\Mike\Desktop\Earthquake Feed Listener Engine\file.py" "C:\Users\Mike\Desktop\repo\file.py" -Force
```
After copying, always run `git add` and `git commit` from the repo folder.

---


### 34. Never use urllib.parse.urlencode for USGS API datetime parameters
urlencode() percent-encodes colons in timestamps (T01:00:00 becomes T01%3A00%3A00).
The USGS FDSNWS query API silently returns 0 results when datetimes are colon-encoded.

Use the pre-built GeoJSON summary feeds instead -- they always work, no parameters needed:
  https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson
  https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/significant_month.geojson

If the query API is required, build the URL with an f-string -- never pass time fields through urlencode:
```python
# Correct -- colons survive intact
url = (
    "https://earthquake.usgs.gov/fdsnws/event/1/query"
    f"?format=geojson&starttime={start}&endtime={end}&minmagnitude=5.5"
)

# Wrong -- urlencode turns colons into %3A, API returns 0 results silently
params = urllib.parse.urlencode({"starttime": start, "endtime": end})
```

---

## SESSION HISTORY SUMMARY

### V1 (original)
GPS-TEC coherence only. 4-station Kp gate. TPR=1.00, FPR=0.00 on 8 validated events.

### V2 (completed before V3 session)
Added: DART 28-buoy network, GIRO ionosonde 5 stations, GLONASS+Galileo constellation, dTEC/dt, ShakeMap focal mechanism filter, 4-channel space weather quality score, combined_confidence fusion formula, confidence calibration tracking, V2 scorer.

### V3 (April 26 2026)
Added: Discord webhook alerting (notify_discord.py), historical backtester (backtest.py), CDDIS auth fix (Earthdata session), README updated to V2, rinex_downloader.py CDDIS auth patched, detector_runner.py UTF-8 logging fixed.

### V4 (April 26 2026)
Added: tsunamigenic_weight in combined_confidence (FPR 0.20→0.00), 4 new stations (AUCK/NOUM/KWJ1/HOLB), adaptive_thresholds.py (Bayesian, advisory), D3 Natural Earth Pacific map, near-miss seismic markers, health_check expanded to 20 sections. Fixed pipeline.py duplicate imports.

### V5 (April 26 2026)
Fixed: HOLB geographic zone constraint (FPR=0.00). Dashboard: About tab, footer, GA. Health check section 21 (zone constraint integrity). CLAUDE_CODE_RULES.md rules 1-26.

### V6 (April 28 2026)
Added: Fast poll mode -- 2-min cycles on Mw6.0+ Pacific detection (usgs_listener.py + pipeline.py). Explicit None zone constraints for all unconstrained stations (detector_runner.py). Health check section 21 verified clean. README fully rewritten (7-channel fusion, V5 backtest, 10-station network, 21-section health check). CLAUDE_CODE_RULES.md rules 27-28 added. Pipeline at 315+ polls, 0 scored live events, all systems operational.

### 29. Always end every session with a simple "how to run" block
Every deploy script delivery must include:
- A clear "run this" section at the top of the response
- A single copy-paste PowerShell block using Get-ChildItem wildcard (never quoted .py filenames)
- Any follow-up commands (git, verify) printed by the script itself at the end
Keep it as simple as possible -- Mike should never have to hunt for the run command.
### 29. Always end every deploy with a simple one-liner run command
Every script delivery must open with a clear PowerShell run block using Get-ChildItem wildcard. Never put .py filenames in quoted strings. Mike should never hunt for the run command.

### 30. LF/CRLF git warnings are harmless
Python writes files with newline="\n" (LF). Git on Windows will warn about LF->CRLF conversion on git add. This is expected and does not affect functionality. Never change the Python write pattern to fix this.


### 31. Guard deploy-script checks on function definition, not symbol name
When checking whether a function has already been injected into a file,
always check for the DEFINITION (`'function renderX'` or `'def render_x'`),
NOT just the symbol name (`'renderX'`).
If a caller like `loadDyfi()` was already injected and it calls `renderX(...)`,
a bare `'renderX' not in src` guard will silently skip injecting the definition.

**Never:**
```python
if 'renderDyfiPings' not in html:   # WRONG -- matches call inside loadDyfi()
```

**Always:**
```python
if 'function renderDyfiPings' not in html:   # matches definition only
if 'def render_dyfi_pings' not in src:       # Python equivalent
```


### 32. Every run instruction must be a clean copy-paste block
Never tell Mike to run something without a formatted code block he can copy directly.
No exceptions -- not for one-liners, not for git commands, not for verification checks.
Every instruction = one clean fenced code block. If there are multiple steps, each step
gets its own block in order. Never embed commands in prose sentences.

### 33. Mike is not a developer -- communicate accordingly
Do not assume Mike knows what a function definition is, what an anchor is, what base64
means, or any other dev terminology. When something fails or needs explanation, say what
it does and why it matters in plain language. Technical detail goes in comments inside
scripts -- not in the chat response. Keep responses short, direct, and action-focused.
