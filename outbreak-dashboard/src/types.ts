export type OutbreakLevel = 'informational' | 'elevated' | 'high'

export interface RegionCase {
  id: string
  name: string
  lat: number
  lng: number
  suspected?: number
  probable?: number
  confirmed?: number
  ruled_out?: number
  outbreak_level?: OutbreakLevel
  last_reported?: string
  sources: string[]
}

export interface CasesFile {
  updated: string
  disclaimer: string
  regions: RegionCase[]
}

export interface NewsItem {
  id: string
  title: string
  url: string
  published_at: string | null
  source_name: string
  source_tier: number
  summary?: string
}

export interface NewsFile {
  fetched_at: string
  items: NewsItem[]
}
