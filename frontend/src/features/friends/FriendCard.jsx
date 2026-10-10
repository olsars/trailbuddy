import PixelAvatar from '../../assets/PixelAvatar'

export default function FriendCard({ friend }) {
  const location = friend.locationSharing ? friend.location : null

  return (
    <li className="friend-card">
      <div className="friend-card__avatar">
        <PixelAvatar name={friend.displayName} size={34} />

        {location && (
          <span
            className="friend-card__sharing"
            role="img"
            aria-label="Location sharing enabled"
          />
        )}
      </div>

      <div className="friend-card__details">
        <div className="friend-card__heading">
          <strong>{friend.displayName}</strong>

          {location && (
            <span>{location.distanceMiles.toFixed(1)} mi</span>
          )}
        </div>

        <p>{location ? location.trailName : 'Location not shared'}</p>
      </div>
    </li>
  )
}