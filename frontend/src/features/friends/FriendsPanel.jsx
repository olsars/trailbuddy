import { useState } from 'react'
import FriendCard from './FriendCard'
import './FriendsPanel.css'

export default function FriendsPanel({ friends = [] }) {
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(true)

  const filteredFriends = friends.filter((friend) =>
    friend.displayName.toLowerCase().includes(search.trim().toLowerCase()),
  )

  return (
    <aside className="friends-panel" aria-label="Friends sidebar">
      <header className="friends-panel__header">
        <h1>Trail Buddy</h1>

        <button
          className="friends-panel__menu"
          type="button"
          aria-label={expanded ? 'Collapse friends panel' : 'Expand friends panel'}
          aria-expanded={expanded}
          aria-controls="friends-panel-content"
          onClick={() => setExpanded(!expanded)}
        >
          ☰
        </button>
      </header>

      <div id="friends-panel-content" hidden={!expanded}>
        <div className="friends-panel__search">
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            aria-hidden="true"
          >
            <circle cx="10" cy="10" r="7" />
            <path d="m15 15 6 6" />
          </svg>

          <input
            type="search"
            aria-label="Search friends"
            placeholder="Search Friends"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <h2>Friends:</h2>

        <ul className="friends-panel__list">
          {filteredFriends.map((friend) => (
            <FriendCard key={friend.id} friend={friend} />
          ))}
        </ul>

        {filteredFriends.length === 0 && (
          <p className="friends-panel__empty">
            {friends.length ? 'No friends found.' : 'No friends yet.'}
          </p>
        )}
      </div>
    </aside>
  )
}