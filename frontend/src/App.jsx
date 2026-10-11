import FriendsPanel from './features/friends/FriendsPanel'
import { mockFriends } from './mocks/friends'

export default function App() {
  return (
    <main className="app-layout">
      <FriendsPanel friends={mockFriends} />

      <section className="map-area" aria-label="Map">
        {/* Person 1's map component goes here */}
      </section>
    </main>
  )
}