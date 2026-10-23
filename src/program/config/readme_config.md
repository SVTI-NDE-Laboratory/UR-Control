# Measurement configuration

`config_default.json` is the single measurement preset for automatic commands
and both Webapp2 stop modes. Select `measurement.stop_method: "timer"` or
`"client_feedback"` rather than maintaining separate preset files.

The webapp generates `config_tmp.json` when validating a run. `state.json` stores
runtime state; neither is a measurement preset. Each run writes its own
`config_used.json`. Webapp2 stores these runtime files in its local-data folder.
The acquisition server has a separate, actively used configuration at
`src/program/data_acquisition/config_server.json`.

`config_default.json` defines both real and simulation program paths for
automatic stop modes and in Flexible web/CLI commands. The path is read again
before each automatic start or Flexible force command. A timer preset, an old
validated snapshot, or a hidden browser field cannot override it. Restart the
webapp after updating application code; later path-only file edits are picked
up for new commands without restarting an active Flexible session.

## Current format

```json
{
  "line": {
    "start_point": "p_start_l",
    "end_point": "p_end_l",
    "increment": 200,
    "number_of_measurements": 8,
    "x_start": 0,
    "x_end": 0,
    "offset_y": 0,
    "auto_fit": true,
    "spacing_source": "increment"
  },
  "motion": {
    "type": "l",
    "acceleration": 150,
    "speed": 150
  },
  "measurement": {
    "program_path": "/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_v2.urp",
    "settling_time": 1.5,
    "target_force": 200,
    "simulation_program_path": "/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_simulation_v2.urp",
    "max_displacement": 50,
    "simulation": false,
    "stop_method": "client_feedback",
    "hold_duration": 0.5
  }
}
```

## Line settings

Line fields are stored directly in `line`: there is no `method` selector or
`parameters` wrapper. The measurement line follows the taught Cartesian
`p_start_l` to `p_end_l` direction and keeps the start orientation. Clearance is
derived from `p_start_h` to `p_start_l`.

Distances are in millimetres. X Start is relative to the taught start; X End
uses the same origin. With Automatic Fit on, `x_end: 0` in a default file means
the full taught length. The webapp initializes Start to zero and End to the
exact taught length at startup and whenever Automatic Fit is enabled.

With `auto_fit: true` and `spacing_source: "increment"`, Step Size is preserved
and Nb. Points is `floor((End - Start) / Step) + 1`. With source `"count"`,
Step Size is `(End - Start) / (Count - 1)`, including both ends (Count >= 2).
With fit off, Start, Step Size and Count are independent and End is calculated
as `Start + (Count - 1) * Step` (Count >= 1).

Start and End may extend up to 100 mm beyond the taught endpoints. The webapp
requires explicit confirmation before starting an automatic run in that range.
`offset_y` is a fixed perpendicular offset; it never changes the X grid.
Displayed numbers use up to two decimal places; calculations retain precision.

## Optional obstacles

Add an optional top-level section, alongside `line`, `motion` and `measurement`:

```json
"obstacle": {"start": 300, "end": 500}
```

Obstacle positions are in millimetres from the same taught X origin as Start
and End. Both bounds must be present, ordered and within the taught line.
Obstacles mark existing points as skipped without changing coordinates or
spacing. Path crossings between samples also use the taught Home detour, even
if no sample falls inside the obstacle. Omit `obstacle` to measure every point.

## Motion and force

Traversal uses `motion.type: "l"`, speed in mm/s and acceleration in mm/s^2.
These settings do not change motion inside the controller-side force program.
`program_path` identifies the real URP; `simulation_program_path` identifies
its separate stationary simulation program. `target_force` is positive and in
newtons; `settling_time` is nonnegative and in seconds. Maximum displacement is
positive and in millimetres. `simulation: true` selects a timed cycle that stays
at the current pose and waits for Python's measurement-release acknowledgement.
The real cycle enters force mode once, reaches target, and waits the configured
settling delay before signalling readiness. See `documentation/force_application.md`
for source installation and register mappings.

`measurement.stop_method` accepts exactly two values:

- `"timer"`: Python waits for `measurement.hold_duration` seconds after force
  success, then releases the robot. No external acquisition listener is started.
- `"client_feedback"`: Python waits for the external ISREADY/GO acquisition
  workflow, then releases the robot. Hold Duration is unused and blurred.

Both robot programs use the feedback-release handshake. Python releases the
selected URP by writing input integer register 42 to 1. Float registers 43-45
contain maximum displacement, settling time and target force. Simulation is
selected by its URP path, without an integer simulation register. No register 47 is used. Python handles timing, client timeouts, safety
checks, and the separate 30-second return deadline.

## Older files

Nested point-to-point `line.method`/`line.parameters` configurations are still
readable and are flattened when loaded or saved. The former boolean
`measurement.data_server` is mapped to `stop_method`: false becomes `"timer"`,
true becomes `"client_feedback"`. Saved files use the current schema.
