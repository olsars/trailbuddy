# GPS simulator

Until the Raspberry Pi GPS is connected, the simulator sends a short fake trail
to the backend using only Python's standard library.

With the backend running, start a simulated walk from the repository root:

```powershell
python gps/simulator.py
```

Pass `--walk-id ID` to add points to an existing active walk. Run
`python gps/simulator.py --help` for coordinate, point-count, and timing options.
Use `--user jordan` (or another seeded demo user id) to record the simulated
walk for a different profile. Each simulated point includes its GPS timestamp
so a future ghost can replay the original pace and pauses.
