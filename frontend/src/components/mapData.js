const sampleRoute = [
  [28.6038, -81.2018],
  [28.6031, -81.2002],
  [28.6021, -81.1987],
  [28.6008, -81.1997],
  [28.6009, -81.2020],
  [28.6022, -81.2031],
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
      [28.6075, -81.2045],
      [28.6064, -81.2028],
      [28.6072, -81.2009],
      [28.6082, -81.1998],
    ],
  },
  {
    id: 'laeh',
    label: 'Laeh',
    color: '#a7c985',
    avatarUrl: '/avatars/cat.avif',
    points: [
      [28.5976, -81.1985],
      [28.5984, -81.1968],
      [28.5992, -81.1958],
      [28.6002, -81.1965],
    ],
  },
  {
    id: 'sam',
    label: 'Sam',
    color: '#d2c979',
    avatarUrl: '/avatars/cat.avif',
    points: [
      [28.6012, -81.2085],
      [28.5998, -81.207],
      [28.5988, -81.2053],
    ],
  },
];