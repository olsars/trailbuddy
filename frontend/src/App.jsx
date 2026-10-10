import FriendsPanel from './features/friends/FriendsPanel'
import { mockFriends } from './mocks/friends'

export default function App() {
  return (
    <main style={{ minHeight: '100svh', background: '#1d2338' }}>
      <FriendsPanel friends={mockFriends} />
    </main>
  )
}

