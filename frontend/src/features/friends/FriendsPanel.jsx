import { useState } from 'react'
import FriendCard from './FriendCard'

export default function FriendsPanel({ friends = [] }) {
  const [search, setSearch] = useState('')

  const filteredFriends = friends.filter((friend) =>
    friend.displayName
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  )

  return (
    <aside
      aria-label="Friends"
      style={{
        width: '100%',
        maxWidth: 320,
        minHeight: '100svh',
        padding: '28px 20px',
        background: '#171f27',
        color: '#f3f4ef',
      }}
    >
      <h1
        style={{
          margin: '0 0 30px',
          fontSize: 25,
          fontWeight: 900,
        }}
      >
        Trail Buddy
        <span style={{ color: '#ff8b42' }}>.</span>
      </h1>

      <label
        htmlFor="friend-search"
        style={{
          display: 'block',
          marginBottom: 8,
          fontSize: 13,
        }}
      >
        Search friends
      </label>

      <input
        id="friend-search"
        type="search"
        placeholder="Search by name"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        style={{
          width: '100%',
          padding: '13px 14px',
          border: '1px solid #65717d',
          borderRadius: 12,
          background: '#303a45',
          color: '#fff',
          font: 'inherit',
          fontSize: 14,
        }}
      />

      <h2
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          margin: '30px 0 8px',
          fontSize: 16,
        }}
      >
        Friends
        <span style={{ color: '#a8b6ad' }}>{friends.length}</span>
      </h2>

      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {filteredFriends.map((friend) => (
          <FriendCard key={friend.id} friend={friend} />
        ))}
      </ul>

      {filteredFriends.length === 0 && (
        <p style={{ color: '#a8b6ad', fontSize: 14 }}>
          {friends.length === 0
            ? 'Your friends will appear here.'
            : 'No friends match your search.'}
        </p>
      )}

      <p
        style={{
          marginTop: 32,
          padding: 14,
          borderRadius: 12,
          background: '#22312e',
          color: '#b9d9c9',
          fontSize: 12,
          lineHeight: 1.6,
        }}
      >
        Location appears only when a friend chooses to share it with you.
      </p>
    </aside>
  )
}