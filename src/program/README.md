# Program entry point

For installation, robot preparation, every control-panel input, session
outputs, safety behavior, and troubleshooting, see the project-level
[`README.md`](../../README.md).

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
in [`webapp/README.md`](webapp/README.md).

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

Direct use asks for terminal confirmation before connecting to the robot. The
web launcher supplies `--operator-confirmed` only after its browser safety
confirmation and read-only Home preflight.

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

When contact is reached, `ISREADY` returns true. The external client records the
data, then sends `GO`. Python acknowledges robot input register 42 only after
`GO` is accepted. A failed force attempt is saved against its measurement index
before traversal stops and recovery begins.

`Ctrl+C`, the web Stop button, robot safety faults, stalled motion, and protocol
timeouts all request a controlled stop. See the root guide for the exact
movement verification, force timeouts, and recovery behavior.
