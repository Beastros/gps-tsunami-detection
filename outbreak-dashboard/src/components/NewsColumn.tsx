import type { NewsItem } from '../types'

type Props = {
  items: NewsItem[]
  fetchedAt: string | null
}

function tierLabel(t: number) {
  if (t <= 1) return 'Official / institutional'
  if (t === 2) return 'Secondary signal'
  return 'Discovery'
}

export function NewsColumn({ items, fetchedAt }: Props) {
  return (
    <section className="panel news-panel">
      <header className="panel-head">
        <h2>Ingested headlines</h2>
        <p className="panel-sub">
          Keyword-filtered RSS (see <code>ingest/sources.yaml</code>). Verify
          every claim at the original URL.
        </p>
        {fetchedAt ? (
          <p className="panel-meta">Feed snapshot: {fetchedAt}</p>
        ) : null}
      </header>
      <ul className="news-list">
        {items.map((n) => (
          <li key={n.id} className="news-item">
            <a href={n.url} target="_blank" rel="noreferrer">
              {n.title}
            </a>
            <div className="news-meta">
              <span>{n.source_name}</span>
              <span className="news-tier">{tierLabel(n.source_tier)}</span>
              {n.published_at ? <span>{n.published_at}</span> : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
