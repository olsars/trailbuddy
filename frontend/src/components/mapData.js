const sampleRoute = [
  [37.9535, -122.5925],
  [37.9545, -122.5900],
  [37.9560, -122.5875],
  [37.9572, -122.5850],
  [37.9565, -122.5820],
  [37.9555, -122.5800],
];

export const sampleUserPoints = sampleRoute.map(([latitude, longitude], index) => ({
  latitude,
  longitude,
  accuracy_meters: 18,
  recorded_at: new Date(Date.UTC(2026, 9, 10, 9, index * 3)).toISOString(),
}));

export const sampleFriendRoutes = [
  {
    id: 'pablo',
    label: 'Pablo',
    color: '#91abc5',
    avatarUrl: '/avatars/cat.avif',
    points: [
      [37.953, -122.5915],
      [37.9542, -122.589],
      [37.9552, -122.586],
      [37.9558, -122.583],
    ],
  },
  {
    id: 'laeh',
    label: 'Laeh',
    color: '#a7c985',
    avatarUrl: '/avatars/cat.avif',
    points: [
      [37.958, -122.5815],
      [37.957, -122.5795],
      [37.956, -122.578],
      [37.9555, -122.576],
    ],
  },
  {
    id: 'sam',
    label: 'Sam',
    color: '#d2c979',
    avatarUrl: '/avatars/cat.avif',
    points: [
      [37.952, -122.579],
      [37.9528, -122.5775],
      [37.9535, -122.5755],
    ],
  },
];