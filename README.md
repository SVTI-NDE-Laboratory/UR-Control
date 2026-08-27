# UR15 Cobot Measurement Program

This project controls a Universal Robots UR15 cobot for force measurements
along a configurable line. The recommended interface is a local FastAPI web
application with one page for configuration, visualization, live progress, and
start/stop control.

The normal sequence is:

```text
verify Home -> start routine -> move along measurement line
-> apply force -> acquire data -> end routine -> Home
```

> **Safety:** This software commands a real industrial robot. Before starting,
> verify the TCP, payload, waypoint data, force direction, obstacle clearance,
> and physical workspace. Keep the emergency stop accessible. Software checks
> complement the robot safety system; they do not replace a risk assessment.

## 1. Requirements

### Computer

- Windows 10 or 11 is recommended. The native folder picker and separate data
  acquisition terminal are implemented for Windows.
- Python 3.10 or newer.
- A modern web browser.
- A wired network connection to the robot controller.

No database, Node.js installation, or external web service is required.

### Python packages

The pinned dependencies are listed in `requirements.txt`:

```text
ur_rtde==1.6.5
fastapi==0.141.1
uvicorn==0.52.3
```

Create and populate a virtual environment from the project root:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell activation is disabled, use the virtual-environment interpreter
directly in every command:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Robot controller

The current code expects:

- Robot IP address: `192.168.3.10`
- Dashboard server: TCP port `29999`
- URScript secondary interface: TCP port `30002`
- RTDE interface: normally TCP port `30004`
- Remote Control mode enabled on the teach pendant
- Robot powered on, brakes released, and robot mode `RUNNING`

The IP is defined in `src/program/commands/run_measurement_sequence.py` and
`src/program/webapp/settings.py`. Update both if the controller address changes.

The computer firewall and network adapter must permit communication with these
ports. A simple connectivity check is:

```powershell
Test-Connection 192.168.3.10
Test-NetConnection 192.168.3.10 -Port 29999
Test-NetConnection 192.168.3.10 -Port 30002
```

## 2. Prepare the robot-side force program

The controller must contain:

```text
Benoit/apply_force.urp
```

Its Script node must contain the current source from:

```text
src/measurement/polyscope_scripts/apply_force_logic_2.script
```

Whenever that local script changes, copy it into the Script node and save the
URP again on the controller. Python loads this URP through the Dashboard server.

The force protocol uses these registers:

| Register | Direction | Meaning |
|---|---|---|
| Integer 42 | Robot -> Python | `0` ready/complete, `1` force reached, `2` distance/time limit, `3` acknowledgement timeout |
| Integer 42 | Python -> Robot | `1` acquisition completed; release the force hold |
| Double 43 | Python -> Robot | Maximum approach distance [m] |
| Double 44 | Python -> Robot | Contact-force threshold [N] |
| Double 45 | Python -> Robot | Holding force [N] |
| Integer 46 | Python -> Robot | Simulation flag |

The script approaches along the positive Z axis of the TCP pose captured at
force-cycle startup. Confirm that this is the intended physical direction.

Current fixed controller-side values are:

- Maximum approach speed: `0.02 m/s`
- Real approach timeout: `10 s`
- Simulation approach timeout: `2 s`
- Python acknowledgement timeout: `10 s`
- Return speed: `0.04 m/s`
- Return acceleration: `0.1 m/s^2`

## 3. Prepare waypoint and routine data

Routine JSON files are stored in:

```text
src/routines/routine_files
```

The web app initially selects `routines_block_diagonal.json`. A usable routine
file must contain:

- A joint target `q` for `Home`
- A routine named `start`
- A routine named `end`
- Cartesian poses `p` for `p_start_h`, `p_start_l`, and `p_end_l` when using
  point-to-point measurements

For point-to-point mode:

- `p_start_l → p_end_l` defines the physical measurement line.
- `p_start_h → p_start_l` defines the safe-height offset.
- The orientation from `p_start_l` is retained along the line.
- X Start and X End select the measured segment along the taught
  `p_start_l -> p_end_l` line. Measurements never go before `p_start_l` or past
  `p_end_l`.
- Optional Y offset shifts the selected segment sideways. Y is perpendicular to
  the X/Z plane using the right-hand rule; Z follows `p_start_h` to `p_start_l`
  only to define that local frame.

Regenerate routine JSON after changing taught waypoints or routine ordering.
The complete export procedure is documented in
`src/routines/read_me_routines.md`. The standard generator is:

```powershell
python src\routines\create_routines_file.py
```

Review every generated target before allowing robot motion. A routine file can
be syntactically valid while containing an outdated physical waypoint or TCP.

## 4. Start the application

From the project root, launch the recommended web interface:

```powershell
.\.venv\Scripts\python.exe src\program\webapp\app.py
```

The application:

1. Selects a free local port on `127.0.0.1`.
2. Prints the control-panel URL.
3. Opens the page in the default browser.
4. Serves FastAPI documentation at `/api/docs` on the same port.

The application itself does not move the robot. Motion starts only after
**Start program**, successful validation, the Home preflight, and the explicit
safety confirmation.

Use the red **×** in the page header to close the application. If a measurement
worker is active, the close action first requests a robot stop.

## 5. Before every run

1. Confirm that the correct TCP and payload are active on the controller.
2. Confirm that the physical setup matches the selected routine file.
3. Clear the robot workspace and check obstacle clearance.
4. Move the cobot manually to the exact taught `Home` joint configuration.
5. Switch the robot to Remote Control mode.
6. Power on the robot and release the brakes.
7. Keep the emergency stop accessible.
8. Review the visualization and all force values before starting.

The preflight requires every actual Home joint to be within `0.005 rad` of the
stored joint target. This is deliberately a joint-space check, not only a TCP
position check.

## 6. Web application inputs

### Measurement Line

**Routine File**

Selects the waypoint and `start`/`end` routine definitions. Point-to-point
geometry is recalculated from the selected file. The default is
`routines_block_diagonal.json`.

**Method**

- **Point to point**: uses `p_start_l → p_end_l`. Total length and safe height
  are derived from the routine file and cannot be edited in the page.
- **Translation**: moves from the current start pose using the configured
  tool-frame line direction, total length, and safe-height direction.

Translation direction vectors are stored in
`src/program/config/config_translation.json`; they are not exposed as normal
page controls. Direction vectors are normalized by the program and cannot be
zero.

**Total Length [mm]**

The physical translation-line length. It must be positive. In point-to-point
mode it is calculated from the two low waypoints.

**Increment [mm] / # Measurements**

Either field can drive spacing:

- Editing the integer measurement count divides the complete line evenly. The
  count includes both the start and end points.
- Editing the increment preserves that exact spacing. Points are placed at
  `0`, `increment`, `2 × increment`, and so on. A remaining partial interval is
  not measured, so the endpoint is included only when it lies on an increment.
- The measurement count itself must be an integer of at least two.
- In point-to-point mode, an increment cannot exceed the line length.

Displayed lengths, configuration files, live state, and measurement-plan line
positions use millimetres.

**X Start / X End [mm]**

Available in point-to-point mode. These values select the measured segment
along `p_start_l -> p_end_l`. X Start defaults to `0`, and X End defaults to
the full taught line length. For example, setting X Start to `100 mm` reduces
the effective line length by `100 mm`.

**Y Offset [mm]**

Available in point-to-point mode. This shifts the selected segment sideways
without changing orientation. After finishing at the high level, the robot moves
back to the taught line at zero Y offset before the regular end routine returns
to `p_start_h` and Home.

### Obstacle

Enable **Obstacle Exists** to define an inclusive start/end interval measured
along the line from its start.

- Positions must be non-negative.
- Start must not exceed end.
- End must not exceed the line length.
- Measurement points inside the interval are omitted.
- Any movement segment crossing the interval rises to the safe plane, even if
  no sampled point lies inside the obstacle.

**Safe Height [mm]** is editable in translation mode. In point-to-point mode it
is derived from `p_start_h → p_start_l` and is locked.

### Measurement Motion

Measurement-line movements are linear:

| Input | Unit | Rule |
|---|---|---|
| Speed | mm/s | Must be positive |
| Acceleration | mm/s^2 | Must be positive |

Start/end routine motions are defined independently inside the selected routine
JSON. Joint steps use `rad/s` and `rad/s^2`; linear steps use `mm/s` and
`mm/s^2`. Blend radii are stored in millimetres.

### Force Measurement

| Input | Unit | Meaning |
|---|---|---|
| Force Contact | N | Threshold that marks physical contact |
| Force Holding | N | Force maintained while data acquisition runs |
| Maximum Displacement | mm | Maximum permitted approach travel |

Rules:

- Contact and holding forces cannot be negative.
- Holding force must be greater than or equal to contact force.
- Maximum displacement must be positive.
- Setting both force values to zero enables simulation.
- One zero and one nonzero force value is invalid.

In real mode, reaching the force threshold starts the holding phase. In
simulation, measured force is ignored and simulated success occurs after two
seconds, or earlier if the distance limit is reached.

### Configuration actions

- **Save as default** validates the displayed values and replaces the saved
  default for the selected method.
- **Reset default** reloads the saved default for the selected method.
- Invalid inputs remain in the form so they can be corrected; the complete form
  is not reset.

Translation and point-to-point defaults are stored separately:

```text
src/program/config/config_translation.json
src/program/config/config_mira.json
src/program/config/config_server.json
```

### Run Measurement

**Data folder**

The base directory for run output. Use **Browse…** to select it with the native
Windows folder picker.

**Show program terminal**

Opens the main measurement worker in a visible terminal. Data-acquisition
control messages are handled by that same worker through the configured TCP
listener.

**Create dated session folder**

Enabled by default. Each successful **Start program** launch generates a new
local-time session ID such as:

```text
2026-08-17_18-04-31-527315
```

With the option enabled, output is written to:

```text
<Data folder>/<session ID>/
```

If disabled, output is written directly into **Data folder**. In that case, a
later run can replace files with the same names.

## 7. What happens after Start program

1. The page validates all displayed inputs.
2. A safety confirmation popup is shown.
3. The web server checks Remote Control, robot mode, safety state, and Home.
4. A new session ID and output location are created.
5. `commands/run_measurement_sequence.py` starts as a measurement worker.
6. The measurement command writes the effective configuration and measurement plan.
7. The measurement command starts the data-acquisition control listener.
8. The measurement command waits until the external client sends `ALIVE` and receives `OK`.
9. The measurement command repeats the robot readiness and Home checks.
10. The `home_to_start` routine moves to the safe measurement start, falling back to `start` for legacy routine files.
11. Every valid line point is approached and verified.
12. The force URP runs.
13. When force is reached, `ISREADY` returns `T`; otherwise it returns `F`.
14. The external client records data, then sends `GO` and receives `ACK`.
15. Python acknowledges input register 42 only after `GO` is received during force hold.
16. The force script releases the hold and returns to its pre-force pose.
17. Python verifies/corrects that return pose before continuing.
18. After the final point, the `end_to_home` routine returns the robot to Home, falling back to `end` for legacy routine files.

The current protocol is documented in `src/program/data_acquisition/protocol.md`.

## 8. Live visualization and controls

During a run, configuration controls are locked. The visualization shows
pending, current, completed, and failed measurement points.

- **Phase** displays a human-readable program phase.
- **Current position [mm]** changes only after the exact lateral/contact pose is
  reached and verified.
- **Progress** changes only after the force/acquisition result is recorded.
- **Stop program** replaces Start while the worker is running. It requests both
  a URScript stop and Dashboard stop before terminating the worker.

Blocking errors appear as browser popups. Routine informational messages remain
in the terminals and timestamped logs.

## 9. Session output files

A normal session folder contains:

| File | Purpose |
|---|---|
| `session.json` | Session ID, creation timestamp, base folder, and resolved output folder |
| `config_used.json` | Exact validated configuration used by main |
| `measurement_plan.json` | Planned measurement positions and per-point results |
| `state.json` | Latest live worker state consumed by the web page |
| `program.log` | Timestamped main-program stdout and stderr |

Both logs are flushed as messages occur. A log line looks like:

```text
[2026-08-17T18:04:31.527+02:00] Data acquisition: requesting measurement.
```

`measurement_plan.json` uses one-based measurement indexes:

```json
{
  "measurement_index": 1,
  "line_position": 0.0,
  "data": {
    "timestamp": "2026-08-17T18:04:34.118+02:00",
    "force_reached": true
  }
}
```

- `line_position` is stored in millimetres.
- The timestamp is the acquisition completion timestamp when acquisition runs.
- A failed force attempt records `force_reached: false` before the run stops.
- Obstacle-skipped points remain listed with `measured: false` and `skip_reason: "obstacle"`.
- Untouched points retain `null` results.
- Files are updated atomically to avoid exposing partially written JSON.

This result structure identifies the first failed or unfinished point for a
future resume feature. Automatic resume is not currently implemented.

## 10. Force and acquisition timing

When real contact is detected:

```text
force_contact reached
→ force_reached = True
→ robot output register 42 = 1
→ maintain force_holding
→ ISREADY returns T
→ external client sends GO
→ Python replies ACK
→ Python input register 42 = 1
→ end force mode
→ return to saved pose
→ robot output register 42 = 0
```

Data-acquisition listener settings are configured in:

```text
src/program/data_acquisition/config_server.json
```

Current defaults are:

| Setting | Default |
|---|---:|
| Host | `127.0.0.1` |
| Port | `5055` |
| Client ready timeout | `30 s` |
| GO wait timeout | `8 s` |

The external client must send `GO` while the robot-side force program is still
holding force. If `GO` arrives too late, Python does not claim a successful
measurement and requests a robot stop.

## 11. Direct command-line operation

The web app is recommended, but the measurement command can be run directly:

```powershell
.\.venv\Scripts\python.exe src\program\main.py
```

`src\program\main.py` is a compatibility wrapper around:

```powershell
.\.venv\Scripts\python.exe src\program\commands\run_measurement_sequence.py
```

It asks for Enter before connecting and uses:

```text
src/program/config/config_mira.json
src/routines/routine_files/routines_block.json
src/program/config/                 as the output folder
```

Available options:

```powershell
python src\program\commands\run_measurement_sequence.py `
  --config C:\path\to\config.json `
  --routines-file C:\path\to\routines.json `
  --output-dir C:\path\to\output
```

`--operator-confirmed` skips the terminal Enter prompt and is intended for the
web launcher after its safety dialog—not for routine manual use.

Direct command execution uses the exact output folder supplied; automatic
dated session-folder creation is a web-app option.

## 12. Safety and reliability behavior

The program continuously checks RTDE safety bits for protective stops,
safeguard stops, emergency stops, safety violations, and safety faults.

Movement completion is based on actual feedback, not merely command dispatch:

- Cartesian targets must be within `1 mm`, within orientation tolerance, and
  settled below the TCP-speed threshold.
- Joint targets must be within their configured tolerance and settled below the
  joint-speed threshold.
- Direct moves must begin within approximately `1 s` and continue making
  progress. A stalled move is stopped rather than waiting for the full
  `30 s` movement deadline.
- Failed direct moves can be retried twice, but only after a clean stop is
  confirmed.
- Zero-blend routine steps are individually verified.
- The measurement pose is verified immediately before force application.
- The pre-force pose is verified again after the force URP returns.

If force is not reached before the distance/time limit, the failure is recorded,
the robot recovers toward `p_start_h`, and the sequence stops without starting
the normal end routine.

## 13. Troubleshooting

### `ModuleNotFoundError: fastapi`, `uvicorn`, or `rtde_receive`

Use the project virtual environment and reinstall requirements:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Browser does not open

Copy the `http://127.0.0.1:<port>/configuration` URL printed in the terminal and
open it manually.

### Robot is not in Remote Control mode

Switch the teach pendant from Manual/Local to Remote Control. Then verify that
the robot is powered on and its brakes are released.

### Unsafe start: robot is not at Home

Move the robot to the exact taught `Home` joint configuration corresponding to
the selected routine file. Do not loosen the check merely to bypass stale or
incorrect waypoint data.

### Robot does not start moving

Check:

- Controller IP and Ethernet connection
- Remote Control and `RUNNING` robot mode
- Active safety/protective stops
- Correct selected routine file
- Valid acceleration and speed
- Dashboard and URScript ports

The program normally reports a no-start condition after approximately one
second instead of waiting for the full motion timeout.

### Force URP cannot be loaded

Confirm that `Benoit/apply_force.urp` exists on the controller and that
`measurement.program_path` matches its controller-visible path.

### Force is never reached

Check the TCP Z+ direction, force sign, contact threshold, holding force,
payload/TCP setup, and maximum displacement. The real controller approach ends
after `10 s` or at the distance limit.

### Acquisition acknowledgement timeout

Check that the external acquisition client can reach the configured listener
host/port and sends `GO` while `ISREADY` is true. Confirm that port `5055` is
free before starting the measurement worker.

### Waypoint is physically wrong although verification succeeds

The robot may be accurately reaching stale routine data. Regenerate the routine
JSON from the latest PolyScope script export and verify the active TCP.

### Output files are missing or overwritten

Use an absolute writable data folder and leave **Create dated session folder**
enabled. When it is disabled, later runs intentionally reuse the same filenames.

## 14. Useful standalone tools

These supported commands are intended for controlled setup, diagnostics, or recovery:

```powershell
python src\program\commands\go_to_waypoint.py
python src\program\commands\run_single_routine.py
python src\program\commands\run_repeated_single_point_measurement.py
```

These remaining examples are focused experiments and utilities:

```powershell
python examples\run_force_approach.py
python examples\run_hardcoded_program.py
python examples\run_hardcoded_point_to_point_program.py
python examples\run_hardcoded_measurements.py
python examples\create_routines.py
```

Read and edit their constants before use. They command the real robot and do
not all provide the same browser confirmation flow as the main application.

## 15. Project structure

```text
data_acquisition_server/     legacy simulated acquisition server
examples/                    focused experimental scripts and utilities
src/measurement/             line planning, traversal, force integration, state
src/program/                 supported command programs, defaults, and FastAPI web app
src/robot/                   robot communication and verified movements
src/routines/                waypoint extraction and routine JSON files
```

Additional focused documentation:

- `src/program/webapp/README.md`
- `src/program/data_acquisition/protocol.md`
- `src/program/config/read_me_config.md`
- `src/robot/README.md`
- `src/routines/read_me_routines.md`
- `data_acquisition_server/README.md`
