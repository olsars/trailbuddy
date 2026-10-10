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
- `PATCH /walks/{walk_id}/sharing`
- `GET /feed`

A walk starts private. Its owner can change its sharing with:

```json
{
  "visibility": "friends",
  "allow_follow_race": true
}
```

Walk visibility and permission to follow or race are intentionally separate.
The demo header is not authentication and must be replaced before a production
deployment.

Run the backend tests from the repository root:

```powershell
python -m unittest backend.test_main -v
```
