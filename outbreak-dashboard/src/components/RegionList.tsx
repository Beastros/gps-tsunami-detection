import type { RegionCase } from '../types'

type Props = {
  regions: RegionCase[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

function chip(level: RegionCase['outbreak_level']) {
  const lv = level ?? 'informational'
  return <span className={`chip chip-${lv}`}>{lv}</span>
}

export function RegionList({ regions, selectedId, onSelect }: Props) {
  return (
    <section className="panel region-panel">
      <header className="panel-head">
        <h2>Regions (curated ledger)</h2>
        <p className="panel-sub">
          Counts are illustrative samples until you promote items from news
          feeds with citations.
        </p>
      </header>
      <ul className="region-list">
        {regions.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              className={
                r.id === selectedId ? 'region-row active' : 'region-row'
              }
              onClick={() => onSelect(r.id === selectedId ? null : r.id)}
            >
              <div className="region-title">
                <strong>{r.name}</strong>
                {chip(r.outbreak_level)}
              </div>
              <div className="region-counts">
                <span title="Confirmed">C {r.confirmed ?? 0}</span>
                <span title="Probable">P {r.probable ?? 0}</span>
                <span title="Suspected">S {r.suspected ?? 0}</span>
              </div>
              {r.last_reported ? (
                <div className="region-meta">Updated {r.last_reported}</div>
              ) : null}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
