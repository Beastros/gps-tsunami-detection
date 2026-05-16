@echo off
setlocal
REM GPS Tsunami — one Task Scheduler cycle: pipeline + git push to refresh dashboard JSON.
REM Run from repo root (e.g. C:\Users\Mike\Desktop\repo). Task name: GPS Tsunami Master

cd /d "%~dp0"
if errorlevel 1 exit /b 1

set LOG=task_runner.log
echo.>>"%LOG%"
echo ===== %date% %time% =====>>"%LOG%"

python pipeline.py --once >>"%LOG%" 2>&1
if errorlevel 1 (
  echo Pipeline exit code %errorlevel% — running USGS listener only>>"%LOG%"
  python usgs_listener.py --once >>"%LOG%" 2>&1
)

git pull --rebase origin main >>"%LOG%" 2>&1
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
