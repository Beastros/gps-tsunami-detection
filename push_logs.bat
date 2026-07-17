@echo off
REM Legacy helper — prefer run_and_push.bat (runs pipeline + push).
REM Pushes JSON already written in THIS repo folder (no copy from other paths).

cd /d "%~dp0"
git pull --rebase origin main
git add poll_log.json running_log.json event_queue.json dyfi_pings.json
git diff --cached --quiet || (
  git commit -m "Auto-update logs %date% %time%"
  git push origin main
  if errorlevel 1 (
    echo git push FAILED — GitHub token may be expired. Renew at https://github.com/settings/tokens
    exit /b 1
  )
)
