@echo off
setlocal EnableExtensions
REM GPS Tsunami — Task Scheduler: poll USGS + push JSON to GitHub (dashboard feed).
cd /d "%~dp0" || exit /b 1

set LOG=task_runner.log
echo.>>"%LOG%"
echo ===== %date% %time% =====>>"%LOG%"

REM Prefer Windows Python launcher; fall back to python on PATH
set PY=py -3
where py >nul 2>&1 || set PY=python

%PY% -m pip install -q -r requirements.txt >>"%LOG%" 2>&1

REM Always refresh poll_log first (dashboard heartbeat)
%PY% usgs_listener.py --once >>"%LOG%" 2>&1
if errorlevel 1 echo usgs_listener FAILED>>"%LOG%"

%PY% dyfi_poller.py >>"%LOG%" 2>&1

%PY% pipeline.py --once >>"%LOG%" 2>&1
if errorlevel 1 echo pipeline.py exit %errorlevel%>>"%LOG%"

git pull --rebase origin main >>"%LOG%" 2>&1
if errorlevel 1 (
  echo git pull --rebase FAILED>>"%LOG%"
  git rebase --abort >>"%LOG%" 2>&1
  git reset --hard origin/main >>"%LOG%" 2>&1
  %PY% usgs_listener.py --once >>"%LOG%" 2>&1
)

git add poll_log.json running_log.json event_queue.json dyfi_pings.json
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Auto-update pipeline logs %date% %time%" >>"%LOG%" 2>&1
  git push origin main >>"%LOG%" 2>&1
  if errorlevel 1 echo git push FAILED>>"%LOG%"
) else (
  echo No JSON changes to push>>"%LOG%"
)

endlocal
