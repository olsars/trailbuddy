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

Run the backend tests from the repository root:

```powershell
python -m unittest backend.test_main -v
```
