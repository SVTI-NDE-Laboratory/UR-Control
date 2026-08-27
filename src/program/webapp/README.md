# FastAPI web control panel

Install the project dependencies and run:

```powershell
python src\program\webapp\app.py
```

Uvicorn serves the FastAPI application on a free local `127.0.0.1` port and
opens it in the default browser. The web layer is an operator interface around
the robot modules; the complete measurement sequence is the command in
`../commands/run_measurement_sequence.py`.

## Single-page workflow

The Configuration page contains the complete operator workflow. It selects the
routine file, edits and visualizes measurement parameters, starts or stops the
measurement program, and shows live progress in the same visualization used
while editing. A fresh app starts in point-to-point mode with
`routines_block_diagonal.json`; the routine selector is part of the Measurement
Line box.

**Start program** first checks the displayed values, creates the measurement
plan, and writes `../config/config_tmp.json`. An invalid value is reported and
the robot program is not launched. **Save as default** performs the same checks
and explicitly replaces the
default for the selected mode: `config_translation.json` or
`config_mira.json`. **Reset default** reloads that mode's saved
default. Configuration values are locked while the program is running.

Point-to-point geometry is fixed to `p_start_l → p_end_l`; safe clearance is
derived from `p_start_h → p_start_l`. The routine-file selector supplies those
waypoints and passes the same file to the measurement worker. The initial
selection is `routines_block_diagonal.json`. Increment and measurement count
remain synchronized and either value can drive the spacing. An arbitrary
point-to-point increment is preserved; when it does not divide the line exactly,
only complete increments are measured. A remaining partial interval at the end
is not measured. The displayed measurement count is always an integer. When the
operator edits that integer count directly, the exact internal increment divides
the complete line evenly and includes the endpoint. Linear distances and
measurement motion speeds in the form, saved config, live state, and plan are
stored in millimetres, mm/s, and mm/s^2.

Starting requires an explicit safety confirmation and a read-only Home-position
preflight. `commands/run_measurement_sequence.py` then runs as a separate
worker process. The selected output folder receives `config_used.json`,
`state.json`, `measurement_plan.json`, and `program.log`. The log is updated in
real time and prefixes terminal lines with local ISO timestamps. Each program
start generates a fresh local date-and-time session ID. The
**Create dated session folder** checkbox is enabled by default and stores the
complete run under `<selected folder>/<session ID>/`, including a `session.json`
file containing the ID, timestamp, and resolved paths. If unchecked, the
selected folder itself is used. Plan points use one-based `measurement_index` values and are
updated atomically after every force cycle with an ISO timestamp and
`force_reached` result. The log mirrors the same stdout and stderr information
shown in a visible program terminal.

## Layout

```text
webapp/
  app.py                  Uvicorn startup and browser opening
  server.py               FastAPI page and JSON endpoints
  models.py               typed API request bodies
  config_form.py          configuration parsing and HTML form generation
  launcher.py             subprocess construction and Home preflight
  worker_manager.py       measurement worker lifecycle and stopping
  settings.py             paths and UI constants
  pages/
    configuration.html
  static/
    styles.css
```

The FastAPI interactive API documentation is available at `/api/docs` while
the control panel is running.
