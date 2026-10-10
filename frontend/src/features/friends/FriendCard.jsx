import PixelAvatar from '../../components/PixelAvatar'

export default function FriendCard({ friend }) {
  const location = friend.locationSharing ? friend.location : null

  return (
    <li
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '16px 0',
        borderBottom: '1px solid #2c3640',
      }}
    >
      <PixelAvatar name={friend.displayName} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
          }}
        >
          <strong style={{ fontSize: 14 }}>
            {friend.displayName}
          </strong>

          {location && (
            <span style={{ color: '#c0c9c5', fontSize: 12 }}>
              {location.distanceMiles.toFixed(1)} mi away
            </span>
          )}
        </div>

        <p
          style={{
            margin: '6px 0 0',
            color: '#a8b6ad',
            fontSize: 12,
          }}
        >
          {location ? location.trailName : 'Location not shared'}
        </p>
      </div>
    </li>
  )
}