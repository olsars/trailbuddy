export default function PixelAvatar({ name, size = 34 }) {
  return (
    <img
      src="/avatars/cat.avif"
      alt={`${name}'s cat avatar`}
      width={size}
      height={size}
      style={{
        display: 'block',
        boxSizing: 'border-box',
        flexShrink: 0,
        objectFit: 'contain',
        imageRendering: 'pixelated',
        borderRadius: '50%',
        padding: 3,
      }}
    />
  )
}