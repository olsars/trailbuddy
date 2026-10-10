export default function PixelAvatar({ name, size = 44 }) {
  return (
    <img
      src="/avatars/cat.avif"
      alt={`${name}'s cat avatar`}
      width={size}
      height={size}
      style={{
        display: 'block',
        flexShrink: 0,
        objectFit: 'contain',
        imageRendering: 'pixelated',
        background: '#e9dfbd',
        border: '2px solid #42536b',
        borderRadius: '50%',
        padding: 4,
      }}
    />
  )
}