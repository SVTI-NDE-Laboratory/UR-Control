# UR15 Cobot Measurement Program

This project runs force measurements with a Universal Robots UR15 cobot along a
configured measurement line. The current recommended workflow is
point-to-point: the line is derived from taught waypoints in PolyScope, then the
Python program moves between verified targets, applies force, and either talks
to the external data-acquisition client through a local TCP server or lets the
MIRA robot program handle acquisition internally.

Normal sequence:

```text
Home
-> taught start routine
-> point-to-point measurement line
-> apply force
-> acquire data with server or MIRA
-> taught end routine
-> Home
```

Safety: this software commands a real industrial robot. Before starting,
verify the TCP, payload, waypoint data, force direction, obstacle clearance, and
physical workspace. Keep the emergency stop accessible. Software checks help,
but they do not replace a proper risk assessment.

## 1. Requirements

- Windows 10 or 11 is recommended.
- Python 3.10 or newer.
- A wired network connection to the robot controller.
- Universal Robots controller in Remote Control mode.
- Robot powered on, brakes released, and robot mode `RUNNING`.

Install Python dependencies from the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell activation is blocked, call the interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The robot IP is currently:

```text
192.168.3.10
```

It is defined in `src/program/commands/run_measurement_sequence.py` and
`src/program/webapp/settings.py`. Update both if the controller address changes.

Useful connectivity checks:

```powershell
Test-Connection 192.168.3.10
Test-NetConnection 192.168.3.10 -Port 29999
Test-NetConnection 192.168.3.10 -Port 30002
```

## 2. Robot Programs For Force Measurement

The Python program loads a URP on the robot controller for each force cycle.
The selected URP is configured with `force.program_path`.

The real program uses `src/measurement/polyscope_scripts/apply_force_from_ur_settling.script`.
Set its controller URP in `force.program_path`. The identical `apply_force.script`
is also provided. The guarded travel simulation uses `apply_force_simulation.script`, with
its controller URP selected by `force.simulation_program_path`.

Copy each source into its PolyScope Script node and save its URP on the controller.
Local source changes do not update a controller-side program.

The real cycle enters force mode once, reaches `target_force`, waits `settling_time`,
then reports readiness. Python's timer or acquisition client releases the hold.
Simulation moves the configured distance along starting TCP Z+ at up to 5 mm/s,
then uses the same settling delay and release handshake before returning. It
monitors resultant XYZ force throughout: a 40 N guard stops and aborts in place.
This software guard cannot guarantee a 50 N peak limit during stopping.

Force-program registers:

| Register | Direction | Meaning |
|---|---|---|
| Integer 42 | Robot -> Python | 0 initialized/completed, 1 settled/ready, 2 approach/distance failure |
| Integer 42 | Python -> Robot | 0 before start, 1 measurement completed |
| Double 43 | Python -> Robot | Maximum approach distance [m] |
| Double 44 | Python -> Robot | Settling time [s] |
| Double 45 | Python -> Robot | Target force [N] |

The force approach uses the positive Z axis of the TCP pose captured at the
start of the force cycle. Confirm the active TCP orientation before running.

## 3. Waypoints And Routines

The measurement program does not teach waypoints. Waypoints are taught in
PolyScope, exported as a `.script`, and converted into a routine JSON file.

The latest routine file created in this project is a good reference:

```text
src/routines/routine_files/routines_wall_275_top.json
```

It contains the routine set expected by the point-to-point obstacle logic:

| Name | Type | Purpose |
|---|---|---|
| `Home` | waypoint | Required joint target for startup verification |
| `p_start_h` | waypoint | Safe high position above the start side |
| `p_start_l` | waypoint | Low taught start of the physical measurement line |
| `p_end_l` | waypoint | Low taught end of the physical measurement line |
| `p_end_h` | waypoint | Safe high position above the end side |
| `home_to_start` | routine | Move from `Home` to `p_start_h` |
| `start_to_home` | routine | Move from `p_start_h` back to `Home` |
| `home_to_end` | routine | Move from `Home` to `p_end_h` |
| `end_to_home` | routine | Move from `p_end_h` back to `Home` |

Older files with `start` and `end` can still be used for simple cases, but the
four named routines above are the current reference for obstacle handling.

Point-to-point geometry:

- `p_start_l -> p_end_l` defines the physical measurement line.
- `p_start_h -> p_start_l` defines the high-to-low movement.
- `p_end_h -> p_end_l` is used when the robot enters from the end side.
- The orientation from `p_start_l` is retained along the line.
- `x_start` and `x_end` select the measured segment along the taught line.
- `offset_y` shifts the measurement segment sideways.
- Low-level movement along the line keeps the configured Y offset.
- The Y offset is removed only after reaching `p_start_l` or `p_end_l`, before
  moving to the corresponding high point.

Obstacle movement cases are documented in:

```text
movement_cases.md
```

## 4. Creating A Routine File

1. In PolyScope, create a program that contains the waypoint table.
2. Teach at least `Home`, `p_start_h`, `p_start_l`, `p_end_l`, and `p_end_h`.
3. Add any intermediate joint waypoints needed for smooth travel between Home
   and the start/end high points.
4. Export or copy the generated `.script` file into:

```text
src/routines/polyscope_scripts
```

5. Edit `src/routines/create_routines_file.py`.

Set:

- `script_path` to the exported `.script`.
- `output_path` to the routine JSON file to write.
- `home_to_start_waypoints` in order from `Home` to `p_start_h`.
- `end_to_home_waypoints` in order from `p_end_h` to `Home`.
- `additional_waypoint_names` to include `p_start_l` and `p_end_l`.
- `wall_joint_motion` speed, acceleration, and intermediate blend radius.

The current generator uses joint acceleration `0.4 rad/s^2`, speed `2.0 rad/s`,
and `5.0 mm` blend radius on intermediate points. The first and last step of
each routine use `0.0 mm` blend radius so the exact endpoint can be verified.

Generate the file:

```powershell
python src\routines\create_routines_file.py
```

Review the generated JSON before moving the robot. A syntactically correct
routine file can still contain stale or physically wrong waypoint data.

More details:

```text
src/routines/readme_routines.md
```

## 5. Configuration Files

The single measurement default is:

```text
src/program/config/config_default.json
```

Select `force.stop_method` as `client_feedback` for RTM acquisition or
`timer` for a local measurement timer. Webapp2 seeds this file into the active
profile's `measurement_default.json`; both stop modes share that profile.

Important fields:

| Field | Meaning |
|---|---|
| `line.method` | Use `point_to_point` for taught start/end waypoints |
| `line.steps` | Distance between measurement points [mm] when spacing source is `increment` |
| `line.nb_points` | Number of points when spacing source is `count` |
| `line.spacing_source` | Either `increment` or `count` |
| `line.parameters.x_start` | Start offset along `p_start_l -> p_end_l` [mm] |
| `line.parameters.x_end` | End offset along `p_start_l -> p_end_l` [mm]; `0` means full taught length |
| `line.parameters.offset_y` | Sideways offset of the measurement line [mm] |
| `line.parameters.start_point` | Usually `p_start_l` |
| `line.parameters.end_point` | Usually `p_end_l` |
| `motion.acceleration` | Linear movement acceleration along the measurement line [mm/s^2] |
| `motion.speed` | Linear movement speed along the measurement line [mm/s] |
| `force.program_path` | URP loaded for force application |
| `force.settling_time` | Settling delay after first reaching target [s] |
| `force.target_force` | Target force for approach and measurement [N] |
| `force.simulation_program_path` | Guarded travel simulation URP |
| `force.max_displacement` | Maximum force-approach travel [mm] |
| `force.simulation` | Enables simulated force behavior |
| `measurement.data_server` | Enables the Python TCP acquisition server |

Force values must be valid:

- `target_force` must be positive and finite.
- `settling_time` must be nonnegative and finite.
- `max_displacement` must be positive and finite.
- `simulation: true` selects the guarded travel simulation URP.

### Server Configuration

Use `force.stop_method: "client_feedback"` when the independent
data-acquisition client should control acquisition timing.

Typical values:

```json
{
  "measurement": {
    "program_path": "/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp",
    "stop_method": "client_feedback"
  }
}
```

When `stop_method` is `client_feedback`, the measurement worker starts the TCP acquisition
server from:

```text
src/program/data_acquisition/config_server.json
```

Current default endpoint:

```text
127.0.0.1:5055
```

The external client sends simple ASCII commands:

| Command | Response | Bytes |
|---|---|---:|
| `ALIVE` | `ACK` | 3 |
| `START_FIRST` | `ACK` | 3 |
| `ISREADY` | `T` or `F` | 1 |
| `GO` | `ACK` | 3 |

Non-trivial responses, such as unsupported-command errors, use:

```text
[4 byte signed I32 length][UTF-8 data]
```

Detailed protocol:

```text
src/program/data_acquisition/server_protocol.md
```

Simulation with `stop_method: "client_feedback"` still uses the TCP server. Simulation only
simulates the force-contact part; Python still waits for the client `GO` before
it releases the force program.

### Timer Configuration

Set `force.stop_method` to `timer` and `force.hold_duration` to the
measurement duration in seconds. Python starts timing after settling/readiness,
then releases the selected real or simulation URP. No acquisition TCP server is
started in this mode.

## 6. Starting With The Web App

The web app is the recommended interface.

Start it from the project root:

```powershell
.\.venv\Scripts\python.exe src\program\webapp\app.py
```

The terminal prints and opens a local URL like:

```text
http://127.0.0.1:<port>/configuration
```

In the page:

1. Select the routine file, for example `routines_wall_275_top.json`.
2. Select point-to-point mode.
3. Use the force-measurement checkbox to choose Server or MIRA.
4. Review `x_start`, `x_end`, `offset_y`, spacing, speed, and force values.
5. Select the output data folder.
6. Leave "Create dated session folder" enabled for normal runs.
7. Click "Start program".
8. Confirm the safety dialog only after checking the real workspace.

The page then starts the measurement worker, locks the configuration controls,
and displays live state and progress.

## 7. Starting From The Command Line

The compatibility entry point is:

```powershell
.\.venv\Scripts\python.exe src\program\main.py
```

For explicit control, call the measurement command directly:

```powershell
.\.venv\Scripts\python.exe src\program\commands\run_measurement_sequence.py `
  --config src\program\config\config_default.json `
  --routines-file src\routines\routine_files\routines_wall_275_top.json `
  --output-dir C:\path\to\output
```

For timer-based operation, set `force.stop_method: "timer"` in the
measurement configuration. Without `--operator-confirmed`, timer mode asks for
Enter before robot motion. Client-feedback mode waits for the acquisition
client to send `START_FIRST` instead.

## 8. What Happens During A Run

1. The program loads the selected configuration and routine file.
2. It writes `config_used.json`, `measurement_plan.json`, and `state.json` to
   the output folder.
3. If `data_server=true`, it starts the acquisition TCP server and waits for
   the first `ALIVE`.
4. It checks that the robot is running and exactly at the taught `Home` joint
   position.
5. If `data_server=true`, it waits for `START_FIRST`; otherwise it keeps the
   operator safety prompt.
6. If the first measurement point is blocked by an obstacle, it runs
   `home_to_end`; otherwise it runs `home_to_start`.
7. It enters the low measurement line from `p_start_l` or `p_end_l`.
8. It measures each valid point and skips points inside the obstacle interval.
9. If a move to the next point would cross an obstacle, it stays low, returns
   along the offset line to `p_start_l`, removes the Y offset, moves to
   `p_start_h`, goes through Home, then enters again from `p_end_h` and
   `p_end_l`.
10. At each point, Python loads the configured force URP.
11. If force succeeds, acquisition runs through either the TCP server or MIRA.
12. The force URP returns to the pre-force measurement pose.
13. Python verifies that return before moving to the next point.
14. At the end, the robot returns to Home from the side where it finished.

If force is not reached before maximum displacement, the force URP first
returns to the initial low measurement pose. Python then recovers along the low
measurement line to the safe high waypoint on the matching side of the obstacle
and stops the sequence.

## 9. Output Files

A normal run writes:

| File | Purpose |
|---|---|
| `session.json` | Web-created session metadata |
| `config_used.json` | Exact validated configuration used by the worker |
| `measurement_plan.json` | Planned points and results |
| `state.json` | Latest live state for the web page and acquisition server |
| `program.log` | Timestamped worker output |

`measurement_plan.json` stores line positions in millimetres. Obstacle-skipped
points remain listed with `measured: false` and `skip_reason: "obstacle"`.

## 10. Troubleshooting

### Robot Is Not In Remote Control

Switch the teach pendant to Remote Control, power on the robot, and release the
brakes.

### Unsafe Start At Home

Move the robot to the exact taught `Home` joint configuration from the selected
routine file. The startup check is joint-based and uses a tolerance of
`0.005 rad`.

### Force URP Cannot Be Loaded

Confirm that `force.program_path` matches a real program path on the
controller, for example:

```text
Inspection/Programs/apply_force_with_server.urp
Inspection/Programs/apply_force_mira.urp
```

### Acquisition Timeout

For server mode, confirm that the external client can reach the configured host
and port, sends `ALIVE` before startup timeout, sends `START_FIRST` when robot
motion may begin, polls `ISREADY`, and sends `GO` while the robot is waiting in
force hold.

For MIRA mode, `measurement.data_server` should be `false`; otherwise Python
will wait for the external TCP client.

### Waypoint Looks Wrong

Regenerate the routine JSON from the latest PolyScope `.script` export and
verify that the selected routine file is the one used by the run.

## 11. Useful Files

```text
movement_cases.md
src/program/config/readme_config.md
src/program/data_acquisition/readme_data_acquisition.md
src/program/data_acquisition/server_protocol.md
src/program/webapp/readme_webapp.md
src/routines/readme_routines.md
src/robot/readme_robot.md
```

Useful commands:

```powershell
python tools\robot\go_to_waypoint.py
python tools\robot\run_single_routine.py
python src\program\commands\run_repeated_single_point_measurement.py
python examples\run_force_approach.py
python examples\create_routines.py
```

Read and edit command constants before using standalone tools. They can command
the real robot and do not all provide the same confirmation flow as the web app.
