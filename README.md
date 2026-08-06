# UR15 Cobot Control

This folder contains the current Python control program for the UR15 cobot.

The active workflow is Python-driven:

```text
start routine -> measurement line -> end routine
```

Python sends small URScript snippets directly to the robot, waits for feedback,
and then decides the next step. It does not load or start a measurement URP.

## Main Program

Run the complete sequence with:

```powershell
python Code\Program\main.py
```

`main.py` does the following:

1. Reads `Configuration/routines.json`.
2. Reads `Configuration/measurement_config.json`.
3. Starts the simulated data acquisition server.
4. Checks that the robot is in Remote Control mode.
5. Runs the `start` routine.
6. Runs the measurement line.
7. Runs the `end` routine.
8. Stops the simulated data acquisition server.

The script asks for terminal confirmation before connecting and moving.

## Robot Requirements

The robot must have:

- Remote Control mode enabled on the teach pendant.
- Dashboard Server access on port `29999`.
- RTDE access available.
- Primary/script interface access on port `30002`.

If the teach pendant is still in Manual/Local mode, the program raises an error
before sending any movement.

## Routines

Routines are stored in:

```text
Configuration/routines.json
```

The file contains:

- `waypoints`: named robot targets with `p` and/or `q` values.
- `routines`: named ordered waypoint lists.

Current routine flow:

```text
start: Home -> Tmp1 -> Tmp2 -> p_start_h
end:   p_start_h -> Tmp2 -> Tmp1 -> Home
```

Run one routine directly:

```powershell
python Code\Robot\run_routine.py
```

Run the recovery routine script:

```powershell
python Code\examples\run_single_routine.py
```

Move directly to one waypoint:

```powershell
python Code\examples\go_to_waypoint.py
```

Move to a line position while staying high:

```powershell
python Code\examples\go_to_line_position_high.py
```

`run_routine.py` sends one movement at a time and waits for RTDE feedback before
continuing.

Routine JSON helpers live in:

```text
Code\RoutineData
```

`create_routines_file.py` is the only file that creates `Configuration/routines.json`.
After creation, the runtime code uses `read_routines.py` only to read and query
the existing routine file.

`read_routines.py` can return:

- the whole routines file with `read_routines_file(path)`
- one routine with `read_routine(path, name)`
- one waypoint with `read_waypoint(path, name)`
- several waypoints with `read_waypoints(path, names)`

`extract_waypoints_from_script.py` is only used before creation, to extract
waypoint values from a PolyScope `.script` file.

## Measurement Line

The measurement sequence is implemented in:

```text
Code\Measurement\run_measurements.py
```

The robot starts at `p_start_h` after the `start` routine.

For each reachable line position:

1. Move from high to low.
2. Perform the force approach.
3. Acquire data if force was reached.
4. Return linearly to the saved low pose.
5. Move to the next line position.

Obstacle positions are skipped strictly. If the next line point is inside the
obstacle, the robot moves high and jumps directly to the first reachable point
after the obstacle.

At the end of the line, the robot returns high. During the final `end` routine,
the first move back to `p_start_h` is linear so the robot does not take a
joint-space shortcut near the base.

## Measurement Configuration

Measurement parameters are stored in:

```text
Configuration\measurement_config.json
```

The file is organized into:

- `line`: line length, increment, and line direction.
- `obstacle`: obstacle start/end, high-low distance, and high-low direction.
- `measurement`: force approach target, max displacement, acceleration, and speed.
- `data_acquisition`: host, port, and timeout for the simulated acquisition server.

Variable units are documented in:

```text
Configuration\measurement_config_README.md
```

## Force Approach URP

The active force approach is handled by a URP on the robot. Python launches it
and waits for a socket result message.

Python side:

```text
Code\Measurement\force_approach_urp.py
```

Robot-side socket example:

```text
Configuration\Measurement Programs\force_result_socket_example.script
```

The URP should perform the force approach internally, then send one JSON line to
Python before ending:

```json
{"message":"force_approach_done","success":true}
```

or:

```json
{"message":"force_approach_done","success":false}
```

The URP owns the force/max-displacement stop behavior. If Python communication
is lost after the URP starts, the robot-side URP should still finish its own
bounded force routine.

After the force approach:

- data acquisition is requested only if force was reached
- Python returns linearly to the low pose saved immediately before launching the URP

The low pose return is in a `finally` block, so Python attempts it after success,
failure, or an exception while waiting for the URP/acquisition result.

Launch only the force approach test with:

```powershell
python Code\examples\launch_force_approach_urp.py
```

## RTDE Registers

The current main program does not use custom RTDE input or output registers.

Python reads live RTDE feedback instead:

- actual joints with `getActualQ()`
- actual TCP pose with `getActualTCPPose()`
- actual TCP speed with `getActualTCPSpeed()`
- actual TCP force with `getActualTCPForce()`

The old register workflow used `rtde_io.setInputDoubleRegister()`, which is
Python -> robot. The current force approach needs robot -> Python feedback, so
it avoids custom registers and uses the live RTDE state above.

To diagnose robot/RTDE output register mapping without moving the robot, run:

```powershell
python Code\examples\test_output_int_registers.py
```

## Data Acquisition Server

The simulated acquisition server is in:

```text
Data Acquisition Server\data_acquisition_server.py
```

`main.py` starts and stops it automatically.

The measurement code sends a JSON message:

```json
{
  "message": "acquire_data",
  "request_id": "...",
  "tcp_pose": [...],
  "tcp_force": [...]
}
```

The server waits for a simulated acquisition time and replies with:

```json
{
  "message": "data_acquired"
}
```

Start the server manually only when testing it by itself:

```powershell
python "Data Acquisition Server\data_acquisition_server.py"
```
