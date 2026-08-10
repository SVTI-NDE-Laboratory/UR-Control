# Robot routine execution

`run_routine.py` receives routine data loaded from a JSON file such as:

```text
src/routines/routine_files/routines.json
```

Routine file reading and lookup lives in:

```text
src/routines/read_routines.py
```

It runs a named routine by sending one `movej` at a time to the robot on port
`30002`. After each command, it uses RTDE to wait until the actual joints match
the target joints.

Before motion, the scripts query the Dashboard server with `is in remote control`.
If the robot is still in Manual/Local mode on the teach pendant, they raise an
error before sending any movement.

`run_routine.py` provides the reusable routine function used by the main
program and the retained routine example.

Routine moves normally use `q` joint targets with `movej`. When
`linear_first_waypoint=True`, the first waypoint uses its `p` Cartesian target
with `movel`.

## Recovery Routine

`examples/run_single_routine.py` runs one routine only. It is useful if the main program
gets interrupted and you want to return to a known position.

By default it runs:

```python
ROUTINE_NAME = "end"
LINEAR_FIRST_WAYPOINT = False
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
