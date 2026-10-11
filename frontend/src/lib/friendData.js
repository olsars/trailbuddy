// Turns the backend's friend data into what FriendsPanel and WalkMap show.
// `get(path)` is any function that fetches JSON from the backend as the current user.
const COLORS = ['#91abc5', '#a7c985', '#d2c979', '#c99ab5']
const METERS_PER_MILE = 1609.344

// A live walk has no summary yet, so measure it from its points.
function pathMeters(points) {
  const toRad = (degrees) => (degrees * Math.PI) / 180
  let total = 0

  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]
    const b = points[i]
    const h =
      Math.sin(toRad(b.latitude - a.latitude) / 2) ** 2 +
      Math.cos(toRad(a.latitude)) *
        Math.cos(toRad(b.latitude)) *
        Math.sin(toRad(b.longitude - a.longitude) / 2) ** 2

    total += 2 * 6371000 * Math.asin(Math.sqrt(h))
  }

  return total
}

// GET /users/{id}/walks is newest-first: prefer a walk that is still going.
function pickWalk(walks) {
  return walks.find((walk) => walk.status === 'active') ?? walks[0] ?? null
}

export async function loadFriendData(get, friends, shared, avatarUrl) {
  const sharedById = new Map(shared.map((entry) => [entry.user.id, entry]))

  const details = await Promise.all(
    friends.map(async (friend) => {
      const entry = sharedById.get(friend.id)
      if (!entry) return { friend, entry: null, walk: null, points: [] }

      try {
        const walk = pickWalk(await get(`/users/${encodeURIComponent(friend.id)}/walks`))
        const points = walk
          ? await get(`/walks/${encodeURIComponent(walk.id)}/points`)
          : []
        return { friend, entry, walk, points }
      } catch {
        // One friend's trouble must not hide everyone else: keep their card, skip their route.
        return { friend, entry, walk: null, points: [] }
      }
    }),
  )

  const friendCards = details.map(({ friend, entry, walk, points }) => {
    const live = walk?.status === 'active' && !entry?.last_location?.is_stale
    const meters = walk?.summary?.distance_meters ?? pathMeters(points)

    return {
      id: friend.id,
      displayName: friend.display_name,
      avatar: friend.avatar,
      locationSharing: Boolean(entry),
      location: entry
        ? {
            trailName: live ? 'Walking now' : 'Last seen',
            distanceMiles: meters / METERS_PER_MILE,
          }
        : null,
    }
  })

  const friendRoutes = details
    .filter(({ entry }) => entry)
    .map(({ friend, entry, points }, index) => {
      const route = points.map((point) => [point.latitude, point.longitude])
      const last = entry.last_location

      return {
        id: friend.id,
        label: friend.display_name,
        color: COLORS[index % COLORS.length],
        avatarUrl,
        // No visible walk: fall back to the last place they shared, so they still get a pin.
        points: route.length ? route : last ? [[last.latitude, last.longitude]] : [],
      }
    })

  return { friendCards, friendRoutes }
}