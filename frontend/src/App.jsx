import FriendsPanel from './features/friends/FriendsPanel'
import { mockFriends } from './mocks/friends'
import WalkMap from './components/WalkMap'
import { sampleFriendRoutes, sampleUserPoints } from './components/mapData'

export default function App({
  userPoints = sampleUserPoints,
  friendRoutes = sampleFriendRoutes,
}) {
  return (
    <main className="app-layout">
      <FriendsPanel friends={mockFriends} />

      <section className="map-area" aria-label="Map">
        <WalkMap userPoints={userPoints} friendRoutes={friendRoutes} />
      </section>
    </main>
  )
}