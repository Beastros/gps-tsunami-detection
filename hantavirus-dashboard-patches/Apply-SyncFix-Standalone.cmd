@echo off
REM Copy this file into C:\Users\Mike\dev\hantavirus-dashboard and double-click it.
setlocal
cd /d "%~dp0"

if not exist "package.json" (
  echo Not in hantavirus-dashboard repo. Copy this .cmd next to package.json.
  pause
  exit /b 1
)

if not exist scripts mkdir scripts

echo Downloading...
curl -fsSL -o "scripts\Apply-SyncFix-FromUrl.ps1" "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1"
if errorlevel 1 (
  powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1' -OutFile 'scripts\Apply-SyncFix-FromUrl.ps1' -UseBasicParsing"
)

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\Apply-SyncFix-FromUrl.ps1"
echo.
echo Exit code: %ERRORLEVEL%
pause
