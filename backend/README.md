# TrailBuddy backend

From the repository root:

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.main:app --reload
```

If the terminal is already inside the `backend` folder, use:

```powershell
python -m uvicorn main:app --reload
```

The SQLite database is created at `backend/trailbuddy.db`, independent of the
directory the server is launched from. Set `TRAILBUDDY_DB_PATH` to override the
location (the test suite uses this to keep test data isolated).

## Demo users

The backend seeds three profiles so the social flow works without signup:

| User id | Display name | Pixel pet |
| --- | --- | --- |
| `sam` | Sam | Fox |
| `jordan` | Jordan | Bear |
| `maya` | Maya | Frog |

Sam and Jordan begin as friends, and Maya has a pending friend request to Sam.
Requests default to Sam for compatibility with the GPS simulator and the
temporary frontend. To act as another profile, send the demo-only header:

```text
X-Demo-User-Id: jordan
```

Useful endpoints:

- `GET /demo/users` and `GET /demo/me`
- `GET /friends` and `GET /friend-requests`
- `POST /friend-requests`
- `PATCH /friend-requests/{request_id}/accept`
- `GET /walks/{walk_id}` (includes a summary after the walk ends)
- `PATCH /walks/{walk_id}/sharing`
- `POST /walks/{walk_id}/points` and `POST /walks/{walk_id}/points/batch`
- `GET /walks/{walk_id}/points`
- `POST /walks/{walk_id}/events` and `GET /walks/{walk_id}/events`
- `GET /feed`
- `GET /location-sharing` and `PATCH /location-sharing/{friend_id}`
- `GET /locations/shared-with-me` and `GET /locations/{user_id}`

A walk starts private. Its owner can change its sharing with:

```json
{
  "visibility": "friends",
  "allow_follow_race": true
}
```

Walk visibility and permission to follow or race are intentionally separate.
Location sharing is also separate and defaults to off, even for accepted
friends. A user's Last Ping is updated whenever a GPS point is accepted. The
API marks a Last Ping stale after five minutes.

For an intermittently connected Pi, give every point a stable
`client_point_id` and send up to 500 points at once:

```json
{
  "points": [
    {
      "client_point_id": "pi-boot-42-point-1",
      "latitude": 28.6024,
      "longitude": -81.2001,
      "recorded_at": "2026-10-10T16:00:00Z",
      "accuracy_meters": 4.5
    }
  ]
}
```

Repeating a batch is safe: duplicate client IDs are returned but are not stored
again. Safety events use the same pattern with `client_event_id`. Supported
event types are `check_in_requested`, `check_in_confirmed`, `check_in_missed`,
`inactivity_detected`, `movement_resumed`, and `sos_triggered`. Events are kept
private to the walk owner.

Ending a walk stores its point count, Haversine distance, duration, and average
pace in SQLite. These values survive a server restart.

The demo header is not authentication and must be replaced before a production
deployment.

Run the backend tests from the repository root:

```powershell
python -m unittest backend.test_main -v
```
