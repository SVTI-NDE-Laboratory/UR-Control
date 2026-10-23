# Measurement configuration

`config_default.json` is the single measurement preset for automatic commands
and both Webapp2 stop modes. Select `force.stop_method: "timer"` or
`"client_feedback"` rather than maintaining separate preset files.

The webapp generates `config_tmp.json` when validating a run. `state.json` stores
runtime state; neither is a measurement preset. Each run writes its own
`measurement_configuration.json`. Webapp2 stores these runtime files in its local-data folder.
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
    "steps": 200.0,
    "nb_points": 8,
    "x_start": 0.0,
    "x_end": 0.0,
    "offset_y": 0.0,
    "start_point": "p_start_l",
    "end_point": "p_end_l",
    "spacing_source": "steps",
    "auto_fit": true
  },
  "obstacle": {
    "present": false,
    "width": 200.0,
    "position": 100.0,
    "start": 0.0,
    "end": 200.0
  },
  "points_selections": {
    "mode": "all",
    "from_point": 1,
    "point_ids": []
  },
  "force": {
    "program_path": "/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_v2.urp",
    "target_force": 200.0,
    "settling_time": 1.5,
    "max_displacement": 50.0,
    "stop_method": "client_feedback",
    "hold_duration": 5,
    "simulation": false,
    "simulation_program_path": "/programs/Projects/BAM TTS/Programs/Apply_Force/apply_force_simulation_v2.urp"
  },
  "motion": {
    "type": "l",
    "acceleration": 150.0,
    "speed": 150.0
  }
}
```

## Line settings

Files use the section order `line`, `obstacle`, `points_selections`, `force`,
then `motion`. Line spacing is stored as `steps` [mm] and `nb_points`.
Line fields are stored directly in `line`: there is no `method` selector or
`parameters` wrapper. The measurement line follows the taught Cartesian
`p_start_l` to `p_end_l` direction and keeps the start orientation. Clearance is
derived from `p_start_h` to `p_start_l`.

Distances are in millimetres. X Start is relative to the taught start; X End
uses the same origin. With Automatic Fit on, `x_end: 0` in a default file means
the full taught length. The webapp initializes Start to zero and End to the
exact taught length at startup and whenever Automatic Fit is enabled.

With `auto_fit: true` and `spacing_source: "steps"`, Step Size is preserved
and Nb. Points is `floor((End - Start) / Step) + 1`. With source `"nb_points"`,
Step Size is `(End - Start) / (Count - 1)`, including both ends (Count >= 2).
With fit off, Start, Step Size and Count are independent and End is calculated
as `Start + (Count - 1) * Step` (Count >= 1).

Start and End may extend up to 100 mm beyond the taught endpoints. The webapp
requires explicit confirmation before starting an automatic run in that range.
`offset_y` is a fixed perpendicular offset; it never changes the X grid.
Displayed numbers use up to two decimal places; calculations retain precision.

## Optional obstacles

Keep the `obstacle` object at all times. For example:

```json
"obstacle": {"present": true, "width": 200, "position": 400, "start": 300, "end": 500}
```

The automatic form edits only the center, **Position [mm]**. Width is read from
the `obstacle.width` setting (default 200 mm) and is read-only. Start
and End are read-only values calculated as center minus/plus half the width.
The backend also calculates the bounds for CLI runs. Set `present` to false
to disable exclusions while retaining width and position. Imported explicit
start/end intervals retain their center and width.

Obstacle positions are in millimetres from the same taught X origin as Start
and End. When present, the calculated bounds must be ordered and within the taught line.
Obstacles mark existing points as skipped without changing coordinates or
spacing. Path crossings between samples also use the taught Home detour, even
if no sample falls inside the obstacle. Set `obstacle.present` to false to remove obstacle exclusions.

## Points selection

Point IDs are one-based IDs on the full line; selecting a subset never changes
spacing, positions or IDs. Obstacles always exclude points. The automatic form
places **Points selection** between Obstacle and Force measurement:

- **All** (default): measure every valid point.
- **From point**: enter an ID; measure valid points with that ID or higher.
- **Custom**: open the dialog and tick IDs, with X/Y positions shown beside them.

The equivalent top-level JSON for CLI runs is:

```json
"points_selections": {"mode": "custom", "from_point": 1, "point_ids": [2, 9]}
```

Use `"mode": "all"` or `"mode": "from_point"` with `from_point` for the other
choices. Empty effective subsets and invalid IDs are rejected before motion.
The plan retains all original IDs, marking exclusions with `skip_reason` equal
to `obstacle` or `not_selected`. Motion between selected points still uses the
obstacle detour; entry beyond an obstacle uses the end-side taught routine.

## Motion and force

Traversal uses `motion.type: "l"`, speed in mm/s and acceleration in mm/s^2.
These settings do not change motion inside the controller-side force program.
`program_path` identifies the real URP; `simulation_program_path` identifies
its separate guarded travel simulation program. `target_force` is positive and in
newtons; `settling_time` is nonnegative and in seconds. Maximum displacement is
positive and in millimetres. `simulation: true` moves the configured distance along starting TCP Z+ at up to
5 mm/s, settles, waits for Python's measurement-release acknowledgement, then
returns. A 40 N resultant-force guard stops and aborts in place throughout the
cycle. This software guard leaves margin below 50 N but cannot guarantee a
50 N peak limit during stopping.
The real cycle enters force mode once, reaches target, and waits the configured
settling delay before signalling readiness. See `documentation/force_application.md`
for source installation and register mappings.

`force.stop_method` accepts exactly two values:

- `"timer"`: Python waits for `force.hold_duration` seconds after force
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
`force.data_server` is mapped to `stop_method`: false becomes `"timer"`,
true becomes `"client_feedback"`. Saved files use the current schema.

Existing configurations using `measurement`, `points_selection`, top-level
`obstacle_width`, `increment` and `number_of_measurements` remain readable.
Profile startup migrates them to the ordered file format, preserving configured
force values, paths, selected IDs and obstacle dimensions. Defaults, temporary
configs and per-run `measurement_configuration.json` files all use the ordered format.
