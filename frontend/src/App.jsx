import { useEffect, useState } from 'react'
import FriendsPanel from './features/friends/FriendsPanel'
import WalkMap from './components/WalkMap'
import { requestJson } from './lib/request'
import { loadFriendData } from './lib/friendData'

// Which demo user the page acts as: /app/?user=pablo   (default: sam)
// It must be the same user the Pi sends walks as (TRAILBUDDY_USER on the Pi, default pablo).
const DEMO_USER = new URLSearchParams(window.location.search).get('user') || 'pablo'
const AVATAR_URL = `${import.meta.env.BASE_URL}avatars/cat.avif`

// Vite uses the proxy; FastAPI's built app uses direct API paths.
const API_BASE = import.meta.env.DEV ? '/api' : ''

function getData(path, signal) {
  return requestJson(`${API_BASE}${path}`, {
    headers: { 'X-Demo-User-Id': DEMO_USER },
    signal,
  })
}

export default function App() {
  const [userPoints, setUserPoints] = useState([])
  const [friends, setFriends] = useState([])
  const [friendRoutes, setFriendRoutes] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [status, setStatus] = useState('Connecting to backend…')

  useEffect(() => {
    const controller = new AbortController()
    let timer

    async function refresh() {
      try {
        const [locationResult, friendResults, sharedResults] = await Promise.all([
          getData(`/locations/${DEMO_USER}`, controller.signal),
          getData('/friends', controller.signal),
          // If this one fails, your own route should keep updating, so fall back to "nobody is sharing".
          getData('/locations/shared-with-me', controller.signal).catch(() => []),
        ])

        const location = locationResult.last_location

        const points = location?.walk_id
          ? await getData(
              `/walks/${encodeURIComponent(location.walk_id)}/points`,
              controller.signal,
            )
          : location
            ? [location]
            : []

        const friendData = await loadFriendData(
          (path) => getData(path, controller.signal),
          friendResults,
          sharedResults,
          AVATAR_URL,
        )

        if (controller.signal.aborted) return

        setUserPoints(points)
        setFriends(friendData.friendCards)
        setFriendRoutes(friendData.friendRoutes)

        setStatus(
          !location
            ? 'No GPS data yet'
            : location.is_stale
              ? 'Last recorded location is over five minutes old'
              : 'Showing latest recorded location',
        )
      } catch (error) {
        if (controller.signal.aborted) return

        setStatus(`${error.message}. Location updates are paused.`)
      } finally {
        if (!controller.signal.aborted) {
          setInitialLoading(false)
          timer = window.setTimeout(refresh, 3000)
        }
      }
    }

    refresh()

    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [])

  return (
    <main className="app-layout">
      <FriendsPanel friends={friends} />

      <section
        className="map-area"
        aria-label="Map"
        style={{ position: 'relative' }}
      >
        <WalkMap
          userPoints={userPoints}
          friendRoutes={friendRoutes}
          initialLoading={initialLoading}
        />

        <p
          role="status"
          style={{
            position: 'absolute',
            bottom: 16,
            left: 16,
            right: 16,
            zIndex: 1000,
            margin: 0,
            padding: '10px 14px',
            borderRadius: 10,
            background: '#171f27',
            color: '#fff',
            fontSize: 13,
          }}
        >
          {status}
        </p>
      </section>
    </main>
  )
}