import { useState } from 'react'
import FriendCard from './FriendCard'
import './FriendsPanel.css'

export default function FriendsPanel({ friends = [] }) {
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState(false)

  const visibleFriends = collapsed
    ? friends
    : friends.filter((friend) =>
        friend.displayName.toLowerCase().includes(search.trim().toLowerCase()),
      )

  return (
    <aside
      className={`friends-panel ${collapsed ? 'is-collapsed' : ''}`}
      aria-label="Friends sidebar"
    >
      <header className="friends-panel__header">
        <h1 aria-hidden={collapsed}>Trail Buddy</h1>

        <button
          className="friends-panel__menu"
          type="button"
          aria-label={collapsed ? 'Expand sidebar' : 'Condense sidebar'}
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((previous) => !previous)}
        >
          ☰
        </button>
      </header>

      <div
        className="friends-panel__controls"
        aria-hidden={collapsed}
      >
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
            disabled={collapsed}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <h2>Friends:</h2>
      </div>

      <ul className="friends-panel__list">
        {visibleFriends.map((friend) => (
          <FriendCard
            key={friend.id}
            friend={friend}
            collapsed={collapsed}
          />
        ))}
      </ul>

      {!collapsed && visibleFriends.length === 0 && (
        <p className="friends-panel__empty">
          {friends.length ? 'No friends found.' : 'No friends yet.'}
        </p>
      )}
    </aside>
  )
}