import { useEffect, useRef, useState } from 'react'
import type { MapRef } from 'react-map-gl/maplibre'
import { OutbreakMap } from './components/OutbreakMap'
import { NewsColumn } from './components/NewsColumn'
import { RegionList } from './components/RegionList'
import { loadCases, loadNews } from './loadData'
import type { CasesFile, NewsFile } from './types'

export default function App() {
  const mapRef = useRef<MapRef>(null)
  const [cases, setCases] = useState<CasesFile | null>(null)
  const [news, setNews] = useState<NewsFile | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const [c, n] = await Promise.all([loadCases(), loadNews()])
        if (!cancelled) {
          setCases(c)
          setNews(n)
        }
      } catch (e) {
        if (!cancelled)
          setErr(e instanceof Error ? e.message : 'Failed to load data')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedId || !cases) return
    const r = cases.regions.find((x) => x.id === selectedId)
    if (!r) return
    mapRef.current?.flyTo({
      center: [r.lng, r.lat],
      zoom: 5,
      duration: 900,
    })
  }, [selectedId, cases])

  if (err) {
    return (
      <div className="shell">
        <p className="error-banner">{err}</p>
      </div>
    )
  }

  if (!cases || !news) {
    return (
      <div className="shell">
        <p className="loading">Loading dashboard…</p>
      </div>
    )
  }

  return (
    <div className="shell">
      <header className="top">
        <div>
          <h1>Outbreak signals</h1>
          <p className="tag">
            Map + curated counts + RSS ingest — deploy on GitHub Pages
          </p>
        </div>
        <div className="top-meta">
          <span>Cases file: {cases.updated}</span>
        </div>
      </header>

      <p className="disclaimer">{cases.disclaimer}</p>

      <main className="layout">
        <div className="map-pane">
          <OutbreakMap
            regions={cases.regions}
            onSelect={setSelectedId}
            mapRef={mapRef}
          />
        </div>
        <div className="side-pane">
          <RegionList
            regions={cases.regions}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
          <NewsColumn items={news.items} fetchedAt={news.fetched_at} />
        </div>
      </main>

      <footer className="footer">
        <p>
          Replace sample points in <code>public/data/cases.json</code> with
          verified rows (each with source URLs). Tune feeds and keywords in{' '}
          <code>ingest/sources.yaml</code>.
        </p>
      </footer>
    </div>
  )
}
