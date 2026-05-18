# Hantavirus dashboard — sync fix patch

Use this when `git merge cursor/outbreak-dashboard-gh-pages-e7aa` fails (branch never pushed to `hantavirus-dashboard`).

## Quick apply (Windows)

```powershell
cd C:\Users\Mike\dev\hantavirus-dashboard
powershell -ExecutionPolicy Bypass -File .\scripts\Apply-SyncFix-FromUrl.ps1
```

Or download `sync-fix.patch` from this folder on `gps-tsunami-detection` and run `Apply-SyncFix.ps1` from your repo’s `scripts\` folder.

**Raw patch URL (stable after push):**

`https://raw.githubusercontent.com/Beastros/gps-tsunami-detection/main/hantavirus-dashboard-patches/sync-fix.patch`

## What the patch does

- Live JSON on GitHub Pages via jsDelivr (`main`)
- `publish-pages` job after each ingest (fixes stale `dist/`)
- `ingest/sync_regions.py` — region sidebar counts follow the case registry
- UI labels: registry vs regional rollup
