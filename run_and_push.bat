@echo off
setlocal EnableExtensions
REM GPS Tsunami — Task Scheduler: sync with GitHub, poll, push JSON (dashboard feed).
cd /d "%~dp0" || exit /b 1

set LOG=task_runner.log
echo.>>"%LOG%"
echo ===== %date% %time% =====>>"%LOG%"

set PY=py -3
where py >nul 2>&1 || set PY=python

REM Match GitHub first (fixes "dyfi_pings would be overwritten by merge")
git fetch origin main >>"%LOG%" 2>&1
git pull --rebase origin main >>"%LOG%" 2>&1
if errorlevel 1 (
  echo git pull --rebase FAILED>>"%LOG%"
  exit /b 1
)

%PY% -m pip install -q -r requirements.txt >>"%LOG%" 2>&1

%PY% pipeline.py --once >>"%LOG%" 2>&1
if errorlevel 1 echo pipeline.py exit %errorlevel%>>"%LOG%"

git add poll_log.json running_log.json event_queue.json dyfi_pings.json
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "Auto-update pipeline logs %date% %time%" >>"%LOG%" 2>&1
  git pull --rebase origin main >>"%LOG%" 2>&1
  if errorlevel 1 (
    echo git pull --rebase FAILED, retrying>>"%LOG%"
    git rebase --abort >>"%LOG%" 2>&1
    git fetch origin main >>"%LOG%" 2>&1
    exit /b 1
  )
  git push origin main >>"%LOG%" 2>&1
  if errorlevel 1 echo git push FAILED>>"%LOG%"
) else (
  echo No JSON changes to push>>"%LOG%"
)

endlocal
