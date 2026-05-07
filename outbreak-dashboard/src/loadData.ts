import type { CasesFile, NewsFile } from './types'

function basePath(): string {
  const base = import.meta.env.BASE_URL
  return base.endsWith('/') ? base : `${base}/`
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: 'no-store' })
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

export function loadCases(): Promise<CasesFile> {
  return fetchJson<CasesFile>(`${basePath()}data/cases.json`)
}

export function loadNews(): Promise<NewsFile> {
  return fetchJson<NewsFile>(`${basePath()}data/news.json`)
}
