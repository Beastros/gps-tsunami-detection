# Hantavirus dashboard — sync fix patch

Use this when `git merge cursor/outbreak-dashboard-gh-pages-e7aa` fails (branch never pushed to `hantavirus-dashboard`).

## Quick apply (Windows)

**Command Prompt (cmd)** — paste all lines:

```bat
cd C:\Users\Mike\dev\hantavirus-dashboard
if not exist scripts mkdir scripts
curl -fsSL -o scripts\Apply-SyncFix-FromUrl.ps1 https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Apply-SyncFix-FromUrl.ps1
```

**Or** download `Apply-SyncFix-Standalone.cmd` from this folder, copy it into `hantavirus-dashboard`, double-click.

**PowerShell window** (not cmd):

```powershell
cd C:\Users\Mike\dev\hantavirus-dashboard
New-Item -ItemType Directory -Force -Path scripts | Out-Null
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/Apply-SyncFix-FromUrl.ps1" -OutFile .\scripts\Apply-SyncFix-FromUrl.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\Apply-SyncFix-FromUrl.ps1
```

**Raw patch URL (stable after push):**

`https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/sync-fix.patch`

## What the patch does

- Live JSON on GitHub Pages via jsDelivr (`main`)
- `publish-pages` job after each ingest (fixes stale `dist/`)
- `ingest/sync_regions.py` — region sidebar counts follow the case registry
- UI labels: registry vs regional rollup
