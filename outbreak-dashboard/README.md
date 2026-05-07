# Outbreak signals dashboard

Static React dashboard for **map + curated case ledger + RSS ingest**, built with Vite and deployed to **GitHub Pages** from Actions.

## Local development

```bash
cd outbreak-dashboard
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173/`).

## Production build

```bash
npm run build
npm run preview   # optional smoke test of dist/
```

`vite.config.ts` sets `base` from `GITHUB_REPOSITORY` so asset URLs work under `https://<user>.github.io/<repo>/`.

## GitHub Pages (one-time repo settings)

1. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions** (not “Deploy from a branch”).
2. Merge to `main`. The workflow **Outbreak dashboard — GitHub Pages** uploads `outbreak-dashboard/dist`.
3. After the first successful run, open the site at `https://<user>.github.io/<repository>/`.

If the map tiles or JSON fail to load, check the browser console: wrong `base` almost always means the workflow did not receive `GITHUB_REPOSITORY` (it does by default in Actions).

## Data files

| File | Role |
|------|------|
| `public/data/cases.json` | Curated regions, counts, outbreak level, **primary source URLs**. Edit by hand or generate from your own pipeline. |
| `public/data/news.json` | Output of the ingest job; keyword-filtered headlines. |

## Ingest (RSS)

Feeds and keywords live in `ingest/sources.yaml`. Run locally:

```bash
cd outbreak-dashboard/ingest
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

GitHub runs **Outbreak dashboard — ingest RSS** every six hours (and on demand). When `news.json` changes, the workflow commits it to `main`, which triggers a Pages rebuild.

Replace or extend feeds cautiously: respect each site’s terms and robots policy.

## Honest use

Reporting for rare diseases is uneven. Treat the map as **“what we linked and counted under our rules”**, not a complete global surveillance picture. Keep `disclaimer` in `cases.json` accurate.
