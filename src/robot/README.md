# Robot routine execution

`run_routine.py` receives routine data loaded from a JSON file such as:

```text
src/routines/routine_files/routines.json
```

Routine file reading and lookup lives in:

```text
src/routines/read_routines.py
```

It runs a named routine by reading each step's motion dictionary and sending
either `movej` or `movel` to port `30002`. After each command, it uses RTDE to
verify completion.

Before motion, the scripts query the Dashboard server for both Remote Control
and robot mode `RUNNING`. If the robot is in Manual/Local mode, powered off, or
has not had its brakes released, they raise an error before sending movement.

Cartesian moves must reach their target within 1 mm, remain within the
orientation tolerance, and settle below the TCP speed threshold. A target
timeout triggers a controlled stop and up to two retries using the same
absolute target. If all three attempts fail, the error propagates and no force
measurement is started.

Joint moves likewise require both the configured joint-position tolerance and
a low joint speed continuously for a short settling period. The single-waypoint
utility uses a 0.005 rad tolerance and reports the measured final error only
after that verification succeeds.

`run_routine.py` provides the reusable routine function used by the main
program and the retained routine example.

Each step defines `type` (`j` or `l`), `acceleration`, `speed`, and
`blend_radius`. Joint steps use the waypoint's `q` target; linear steps use its
`p` target. The routine is sent as one URScript program so intermediate radii
can blend into the following step; the final radius must be zero.

## Recovery Routine

`examples/run_single_routine.py` runs one routine only. It is useful if the main program
gets interrupted and you want to return to a known position.

By default it runs:

```python
ROUTINE_NAME = "end"
```

Run it:

```powershell
python examples\run_single_routine.py
```

## Single Waypoint

`examples/go_to_waypoint.py` moves directly to one waypoint from the active
`src/routines/routine_files/routines.json` file.

Edit these variables at the top of the file:

```python
WAYPOINT_NAME = "Home"
USE_LINEAR_MOVE = False
```

Run it:

```powershell
python examples\go_to_waypoint.py
```
