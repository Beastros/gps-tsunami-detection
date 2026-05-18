@echo off
REM Run from repo root: C:\Users\Mike\dev\hantavirus-dashboard
setlocal
cd /d "%~dp0"

if not exist "package.json" (
  echo Put this file in your hantavirus-dashboard folder ^(next to package.json^) and run it again.
  exit /b 1
)

if not exist scripts mkdir scripts

echo Downloading Apply-SyncFix-FromUrl.ps1 ...
curl -fsSL -o "scripts\Apply-SyncFix-FromUrl.ps1" "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1"
if errorlevel 1 (
  echo curl failed, using PowerShell...
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1' -OutFile 'scripts\Apply-SyncFix-FromUrl.ps1' -UseBasicParsing"
)

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\Apply-SyncFix-FromUrl.ps1"
exit /b %ERRORLEVEL%
