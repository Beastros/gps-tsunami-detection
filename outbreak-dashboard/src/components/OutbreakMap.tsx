import React, { useMemo, useCallback } from 'react'
import type { MapLayerMouseEvent } from 'maplibre-gl'
import Map, { Layer, Source, type MapRef } from 'react-map-gl/maplibre'
import type { RegionCase } from '../types'
import 'maplibre-gl/dist/maplibre-gl.css'

const MAP_STYLE =
  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

type Props = {
  regions: RegionCase[]
  onSelect: (id: string | null) => void
  mapRef: React.RefObject<MapRef | null>
}

function toGeoJSON(regions: RegionCase[]) {
  return {
    type: 'FeatureCollection' as const,
    features: regions.map((r) => {
      const total =
        (r.confirmed ?? 0) + (r.probable ?? 0) + (r.suspected ?? 0)
      return {
        type: 'Feature' as const,
        properties: {
          id: r.id,
          name: r.name,
          confirmed: r.confirmed ?? 0,
          suspected: r.suspected ?? 0,
          probable: r.probable ?? 0,
          total,
          level: r.outbreak_level ?? 'informational',
        },
        geometry: {
          type: 'Point' as const,
          coordinates: [r.lng, r.lat],
        },
      }
    }),
  }
}

export function OutbreakMap({ regions, onSelect, mapRef }: Props) {
  const geojson = useMemo(() => toGeoJSON(regions), [regions])

  const onClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const f = e.features?.[0]
      const id = f?.properties?.id as string | undefined
      onSelect(id ?? null)
    },
    [onSelect],
  )

  return (
    <div className="map-shell">
      <Map
        ref={mapRef as React.RefObject<MapRef>}
        initialViewState={{
          longitude: -40,
          latitude: -25,
          zoom: 2.2,
        }}
        mapStyle={MAP_STYLE}
        interactiveLayerIds={['outbreak-circles']}
        onClick={onClick}
        style={{ width: '100%', height: '100%' }}
      >
        <Source id="outbreak-points" type="geojson" data={geojson}>
          <Layer
            id="outbreak-circles"
            type="circle"
            paint={{
              'circle-radius': [
                'interpolate',
                ['linear'],
                ['sqrt', ['max', ['get', 'total'], 1]],
                0,
                6,
                1,
                10,
                3,
                18,
                8,
                28,
              ],
              'circle-color': [
                'match',
                ['get', 'level'],
                'high',
                '#f87171',
                'elevated',
                '#fbbf24',
                '#34d399',
              ],
              'circle-opacity': 0.85,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#0c0f14',
            }}
          />
        </Source>
      </Map>
      <div className="map-legend">
        <span className="legend-dot leg-info" /> informational
        <span className="legend-dot leg-elev" /> elevated
        <span className="legend-dot leg-high" /> high
        <span className="legend-note">
          Dot size scales with √(reported signal counts in JSON — edit rules in
          README).
        </span>
      </div>
      <button
        type="button"
        className="map-clear"
        onClick={() => onSelect(null)}
      >
        Clear map selection
      </button>
    </div>
  )
}
