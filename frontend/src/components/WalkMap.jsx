import { useEffect, useMemo } from 'react'
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

function FitRoutes({ positions, fallbackCenter, zoom }) {
  const map = useMap()

  useEffect(() => {
    if (positions.length > 1) {
      map.fitBounds(positions, { padding: [48, 48], maxZoom: 16 })
    } else if (positions.length === 1) {
      map.setView(positions[0], zoom)
    } else {
      map.setView(fallbackCenter, zoom)
    }
  }, [map, positions, fallbackCenter, zoom])

  return null
}

export default function WalkMap({
  userPoints = [],
  friendRoutes = [],
  center = [37.9555, -122.583],
  zoom = 15,
}) {
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
    <div className="walk-map">
      <MapContainer
        center={currentPosition ?? center}
        zoom={zoom}
        className="walk-map__canvas"
        zoomControl={false}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <FitRoutes
          positions={allPositions}
          fallbackCenter={center}
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
              '/avatars/cat.avif',
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
    </div>
  )
}