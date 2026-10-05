# Program entry point

For installation, robot preparation, every control-panel input, session
outputs, safety behavior, and troubleshooting, see the project-level
[`readme_project.md`](../../readme_project.md).

`commands/run_measurement_sequence.py` runs the complete robot sequence:

```text
Home check -> start routine -> measurements -> end routine -> Home
```

The recommended operator interface is the single-page FastAPI control panel:

```powershell
python src\program\webapp\app.py
```

It combines configuration, visualization, live measurement status, and
start/stop control. Its implementation is contained in `webapp/` and described
in [`webapp/readme_webapp.md`](webapp/readme_webapp.md).

## Direct command-line use

The compatibility wrapper can still be run directly:

```powershell
python src\program\main.py
```

The named command entry point is:

```powershell
python src\program\commands\run_measurement_sequence.py
```

By default, it reads:

```text
src/program/config/config_mira.json
src/routines/routine_files/routines_block.json
```

Explicit paths can be supplied when needed:

```powershell
python src\program\commands\run_measurement_sequence.py `
  --config C:\path\to\config.json `
  --routines-file C:\path\to\routines.json `
  --output-dir C:\path\to\output
```

Direct MIRA use asks for terminal confirmation before robot motion. In server
mode, the worker waits for the acquisition client and starts motion only after
the client sends `START_FIRST`.

## How `run_measurement_sequence.py` works

`run_measurement_sequence.py` is the main orchestration layer. It does not
define the geometry, the force routine, or the low-level robot commands itself;
instead it loads configuration and routine files, prepares the run outputs,
starts optional acquisition communication, checks the robot, then delegates
movement and measurement work to the measurement and robot modules.

Startup:

1. `parse_args()` reads the selected config file, routine file, output folder,
   `--operator-confirmed` flag, and optional web start-signal file.
2. `prepare_output_directory()` creates the output directory and mirrors stdout
   and stderr to `program.log`.
3. `load_run_inputs()` reads the routine JSON and measurement config, validates
   them through `read_measurement_config()`, writes `config_used.json`, creates
   `measurement_plan.json`, and chooses the live `state.json` path.
4. `start_acquisition_if_enabled()` starts the TCP acquisition server when
   `measurement.data_server=true`. That server handles `ALIVE`, `START_FIRST`,
   `ISREADY`, `GO`, and `STATE`. Its state provider reads `state.json` and,
   after RTDE is connected, adds live TCP `X/Y` position and movement status.
5. `wait_for_start_permission()` gates the first robot routine. Server mode
   writes `mode="waiting_for_start_first"` and continues only after the
   acquisition client sends `START_FIRST`. MIRA mode keeps the operator prompt
   or web start-signal safety confirmation.

Robot preflight:

1. `verify_robot_startup()` checks that the robot program is running.
2. It opens RTDE receive feedback.
3. It loads the `Home` waypoint from the selected routine file.
4. It writes `{"mode": "checking_home"}` to `state.json`.
5. It requires the robot joints to be within `HOME_JOINT_TOLERANCE` of `Home`.
   If this fails, no movement command is sent.

Robot sequence:

1. `run_robot_sequence()` writes `{"mode": "start_routine"}`.
2. It checks whether the first measurement point is inside an obstacle.
3. If the first point is blocked, it starts from the end side with
   `home_to_end`; otherwise it uses `home_to_start` when available, falling
   back to the legacy `start` routine for older files.
4. After the start routine, it moves to the high start measurement position
   unless the obstacle logic already started from the end side.
5. It writes `{"mode": "measurements"}` and calls `run_measurements()`.
6. When measurements finish, it writes `{"mode": "end_routine"}` and chooses
   the correct return routine based on the side where the traversal ended:
   `start_to_home`, `end_to_home`, or the legacy `end` fallback.
7. After the return routine completes, it writes `{"mode": "idle"}`.

Measurement phase:

`run_measurements()` owns the point-to-point or translation traversal. For each
planned point it updates `state.json` with the current mode, measurement index,
line position, height mode, obstacle status, and last force result. It routes
around obstacles, moves between high and low positions, verifies the exact TCP
target, runs the force URP, and records the result in `measurement_plan.json`.

When server acquisition is enabled, the force routine reaches the force hold
and Python exposes that hold through the TCP server:

1. Client sends `ISREADY`.
2. Server returns `true` only while the robot is holding force.
3. Client records data.
4. Client sends `GO`.
5. Python acknowledges the robot input register and the robot leaves the hold.

If the client sends `STATE`, the server returns a length-prefixed JSON payload
with live `X`, `Y`, `Point`, `Moving`, and `Error` fields.

Failure and cleanup:

`main()` catches the important failure modes and writes a final state:

- unsafe start position: `mode="unsafe_start"` and exit code `3`
- force not reached at a measurement point: `mode="measurement_failed"` and
  exit code `2`
- operator cancellation: `mode="stopped"` and exit code `130`
- unexpected exception: `mode="error"` with the exception type and message

The `finally` block always disconnects RTDE when it was opened and stops the
acquisition server. This cleanup does not command the robot back to Home; stop
and recovery behavior is handled earlier by the measurement and robot modules.

## Runtime and outputs

At startup, main validates the configuration, writes the plan, starts the data
acquisition control listener, and waits for external client messages on the
configured host/port. It then checks the robot state and requires all six joints to be within
`0.005 rad` of the selected routine's `Home` waypoint before sending motion.

The output directory contains:

```text
config_used.json
state.json
measurement_plan.json
program.log
```

Web sessions also contain `session.json` when the dated-session-folder option
is enabled. Both logs are written in real time with local ISO timestamps.

Each entry in `measurement_plan.json` has a one-based `measurement_index`, a
`line_position` in millimetres, and a `data` result. After a force cycle, `data`
records the acquisition timestamp and whether the requested force was reached.
Points excluded by an obstacle remain in the plan with `measured=false` and
`skip_reason="obstacle"` so their original point IDs are visible.

When contact is reached, `ISREADY` returns `true`. The external client records the
data, then sends `GO`. Python acknowledges robot input register 42 only after
`GO` is accepted. A failed force attempt is saved against its measurement index
before traversal stops and recovery begins.

The complete data-acquisition TCP guide is in
[`data_acquisition/readme_data_acquisition.md`](data_acquisition/readme_data_acquisition.md). The exact byte-level
wire contract is in [`data_acquisition/server_protocol.md`](data_acquisition/server_protocol.md).

`Ctrl+C`, the web Stop button, robot safety faults, stalled motion, and protocol
timeouts all request a controlled stop. See the root guide for the exact
movement verification, force timeouts, and recovery behavior.
