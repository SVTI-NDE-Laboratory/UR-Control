# Robot routine execution

`run_routine.py` reads:

```text
Configuration/routines.json
```

Routine file reading and lookup lives in:

```text
Code/RoutineData/read_routines.py
```

It runs a named routine by sending one `movej` at a time to the robot on port
`30002`. After each command, it uses RTDE to wait until the actual joints match
the target joints.

Before motion, the scripts query the Dashboard server with `is in remote control`.
If the robot is still in Manual/Local mode on the teach pendant, they raise an
error before sending any movement.

The example at the bottom runs:

```text
start
```

The script asks for terminal confirmation before connecting and moving.

```powershell
python Code\Robot\run_routine.py
```

Routine moves normally use `q` joint targets with `movej`. When
`linear_first_waypoint=True`, the first waypoint uses its `p` Cartesian target
with `movel`.

## Recovery Routine

`examples/run_single_routine.py` runs one routine only. It is useful if the main program
gets interrupted and you want to return to a known position.

By default it runs:

```python
ROUTINE_NAME = "end"
LINEAR_FIRST_WAYPOINT = True
```

Run it:

```powershell
python Code\examples\run_single_routine.py
```

## Single Waypoint

`examples/go_to_waypoint.py` moves directly to one waypoint from `Configuration/routines.json`.

Edit these variables at the top of the file:

```python
WAYPOINT_NAME = "Home"
USE_LINEAR_MOVE = False
```

Run it:

```powershell
python Code\examples\go_to_waypoint.py
```
