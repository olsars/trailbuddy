import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Circle,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  ZoomControl,
  useMap,
} from 'react-leaflet'
import L from 'leaflet'
import './WalkMap.css'

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => {
    const entities = {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }
    return entities[character]
  })
}

function toLatLng(point) {
  const latitude = Array.isArray(point) ? point[0] : point?.latitude
  const longitude = Array.isArray(point) ? point[1] : point?.longitude

  if (
    !Number.isFinite(latitude) ||
    !Number.isFinite(longitude) ||
    latitude < -90 ||
    latitude > 90 ||
    longitude < -180 ||
    longitude > 180
  ) {
    return null
  }

  return [latitude, longitude]
}

function createAvatarIcon(label, avatarUrl, color, isCurrentUser) {
  const safeLabel = escapeHtml(label)
  const safeAvatarUrl = escapeHtml(avatarUrl)

  return L.divIcon({
    className: 'custom-avatar-pin',
    html: `
      <div class="map-pin ${isCurrentUser ? 'map-pin--current' : ''}" style="--pin-color: ${color}">
        ${isCurrentUser ? '<span class="map-pin__status">You are here</span>' : ''}
        <img class="map-pin__avatar" src="${safeAvatarUrl}" alt="${safeLabel}" />
        ${!isCurrentUser ? `<span class="map-pin__label">${safeLabel}</span>` : ''}
      </div>
    `,
    iconSize: [48, 58],
    iconAnchor: [24, 29],
  })
}

function FitRoutes({ positions, zoom }) {
  const map = useMap()
  const fitted = useRef(false)

  useEffect(() => {
    if (fitted.current || positions.length === 0) return

    fitted.current = true

    if (positions.length > 1) {
      map.fitBounds(positions, {
        padding: [48, 48],
        maxZoom: 16,
        animate: false,
      })
    } else {
      map.setView(positions[0], zoom, { animate: false })
    }
  }, [map, positions, zoom])

  useEffect(() => {
    let timer

    const observer = new ResizeObserver(() => {
      window.clearTimeout(timer)

      timer = window.setTimeout(() => {
        map.invalidateSize({ pan: false })
      }, 100)
    })

    observer.observe(map.getContainer())

    return () => {
      observer.disconnect()
      window.clearTimeout(timer)
    }
  }, [map])

  return null
}

export default function WalkMap({
  userPoints = [],
  friendRoutes = [],
  center = [28.6024, -81.2001],
  zoom = 15,
  initialLoading = false,
}) {

    const [tileStatus, setTileStatus] = useState('loading')
  const loadedTiles = useRef(0)

  const tileEvents = useMemo(
    () => ({
      loading() {
        loadedTiles.current = 0
      },
      tileload() {
        loadedTiles.current += 1
      },
      load() {
        setTileStatus(
          loadedTiles.current > 0 ? 'ready' : 'error',
        )
      },
    }),
    [],
  )

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTileStatus((current) =>
        current === 'loading' ? 'error' : current,
      )
    }, 15000)

    return () => window.clearTimeout(timer)
  }, [])

  const loading = initialLoading || tileStatus === 'loading'
  const ready = !initialLoading && tileStatus === 'ready'

  const validUserPoints = useMemo(
    () =>
      userPoints
        .map((point) => ({ point, position: toLatLng(point) }))
        .filter((entry) => entry.position),
    [userPoints],
  )
  const userPositions = useMemo(
    () => validUserPoints.map((entry) => entry.position),
    [validUserPoints],
  )
  const currentPosition = userPositions.at(-1)
  const latestPoint = validUserPoints.at(-1)?.point
  const friends = useMemo(
    () =>
      friendRoutes.map((friend) => ({
        ...friend,
        positions: friend.points.map(toLatLng).filter(Boolean),
      })),
    [friendRoutes],
  )
  const allPositions = useMemo(
    () => [
      ...userPositions,
      ...friends.flatMap((friend) => friend.positions),
    ],
    [userPositions, friends],
  )

  return (
    <div
    className={`walk-map ${ready ? 'is-ready' : ''}`}
    aria-busy={loading}
>
      <MapContainer
        center={currentPosition ?? center}
        zoom={zoom}
        className="walk-map__canvas"
        zoomControl={false}
      >
        <TileLayer
      attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
      url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      eventHandlers={tileEvents}
      />

        <FitRoutes
          positions={allPositions}
          zoom={zoom}
        />
        <ZoomControl position="topright" />

        {userPositions.length > 1 && (
          <Polyline
            positions={userPositions}
            pathOptions={{ color: '#ff7438', weight: 4, opacity: 0.95 }}
          />
        )}

        {friends.map((friend) =>
          friend.positions.length > 1 ? (
            <Polyline
              key={`${friend.id}-route`}
              positions={friend.positions}
              pathOptions={{
                color: friend.color,
                weight: 3,
                opacity: 0.85,
                dashArray: '7 7',
              }}
            />
          ) : null,
        )}

        {currentPosition && Number.isFinite(latestPoint?.accuracy_meters) && (
          <Circle
            center={currentPosition}
            radius={latestPoint.accuracy_meters}
            pathOptions={{
              color: '#ff7438',
              fillColor: '#ff7438',
              fillOpacity: 0.15,
              weight: 1,
            }}
          />
        )}

        {currentPosition && (
          <Marker
            position={currentPosition}
            icon={createAvatarIcon(
              'You',
              `${import.meta.env.BASE_URL}avatars/cat.avif`,
              '#ff7438',
              true,
            )}
          />
        )}

        {friends.map((friend) => {
          const lastPosition = friend.positions.at(-1)
          if (!lastPosition) return null

          return (
            <Marker
              key={`${friend.id}-marker`}
              position={lastPosition}
              icon={createAvatarIcon(
                friend.label,
                friend.avatarUrl,
                friend.color,
                false,
              )}
            />
          )
        })}
      </MapContainer>
      <div
  className={`map-loading ${ready ? 'map-loading--hidden' : ''}`}
  aria-hidden={ready}
>
  {loading ? (
    <div role="status" className="map-loading__content">
      <span className="map-loading__spinner" aria-hidden="true" />
      <strong>Finding your trail…</strong>
      <span>
        {initialLoading
          ? 'Connecting to TrailBuddy'
          : 'Loading the map'}
      </span>
    </div>
  ) : (
    <div role="alert" className="map-loading__content">
      <strong>The map couldn’t load</strong>
      <span>Check your internet connection and try again.</span>

      <button
        type="button"
        onClick={() => window.location.reload()}
      >
        Retry
      </button>
    </div>
  )}
</div>
    </div>
  )
}