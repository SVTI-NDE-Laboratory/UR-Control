# Program entry point

`main.py` runs the complete sequence:

```text
start routine -> measurements -> end routine
```

By default it reads:

```text
src/routines/routine_files/routines_block.json
src/program/config/config.json
```

To edit the measurement settings in a small local browser app and launch the program,
run:

```powershell
python src\program\config_app.py
```

The app opens in the default browser, always loads the defaults from `config.json`, and never modifies that
file. When **Start program** is pressed, it validates the fields, writes
`src/program/config/config_tmp.json`, and launches `main.py` with that temporary
configuration. The data-folder control selects where `config_used.json`,
`state.json`, `measurement_plan.json`, and `program.log` are saved. The control
defaults to the workspace-level `temporary_data` folder. A browser
safety dialog must be confirmed before the robot program starts in the
background. The same blue **Start program** button becomes a red **Stop
program** button while the worker is active. Stopping is immediate and has no
confirmation dialog: it commands the cobot to stop before terminating Python.
Select **Show program terminal** before starting to run the worker in a visible
console; leave it clear to run hidden and save its output in `program.log`.
The Obstacle section has separate checkboxes for an obstacle interval and for
the minimum high/low travel distance. Enabling an obstacle automatically
enables and requires the minimum distance. With both options disabled, the run
configuration contains no obstacle section and every line point is measured.
The compact measurement-line controls show both increment and number of
measurements. The count includes both endpoints (`floor(total length /
increment) + 1`); editing the count evenly spaces those points using `total
length / (count - 1)`. Measurement motion is fixed to linear (`l`) and is shown
read-only.
The static page, styling, and browser JavaScript live in
`config/config_app.html`; `config_app.py` loads that template once and only
substitutes the current configuration controls and run state.

**Close app** in the upper-right corner stops the cobot and worker first when a
program is active, then shuts down the local web server and closes the browser
tab when the browser permits scripted tab closure.

`main.py` can also be given a configuration explicitly:

```powershell
python src\program\main.py --config path\to\config.json
```

By default it writes these files in `src/program/config`; `--output-dir` or the
control panel's data-folder control can select another folder:

```text
config_used.json
state.json
measurement_plan.json
program.log (control-panel runs)
```

`measurement_plan.json` is regenerated from the active configuration when the
program starts. It contains the original line index, the position in metres,
and an empty `data` object for future results. Positions inside the obstacle
interval are not included.

Data acquisition is not currently part of this sequence. The optional placeholder
implementation is kept separately in `data_acquisition_server`.

When run directly, the script asks for terminal confirmation before connecting
and moving. The control panel uses its browser safety confirmation instead.
`Ctrl+C` stops any active routine or measurement before Python exits. Robot
safety stops and faults are also detected from RTDE feedback and reported in
`state.json` as errors.

Both direct and control-panel launches perform a read-only startup interlock:
all six joints must be within 0.005 rad of the joint-only `Home` waypoint. The
program sends no motion command if this check fails.

If a real force cycle reaches maximum displacement without detecting contact,
the measurement traversal stops. The robot first rises from the low measurement
pose to the high plane, translates back along the line to `p_start_h`, and then
reports the failed line index and position in the terminal and `state.json`.
The normal end routine is not run after this failure.

```powershell
python src\program\main.py
```
