# UR15 Cobot Control

The active program is:

```powershell
python src\program\main.py
```

For a browser-based configuration editor and launcher, run:

```powershell
python src\program\config_app.py
```

It leaves the default `config.json` unchanged and creates `config_tmp.json`
only when the program is started.

The control panel lets the operator select a data folder for the effective
configuration, live state, measurement plan, and program log. The measurement
plan lists every planned measurement position while excluding positions inside
the obstacle.

During routines and measurements, RTDE safety feedback is monitored for
protective, safeguard, and emergency stops as well as safety faults. These
conditions abort the Python run instead of being mistaken for completed motion.
Pressing `Ctrl+C` in a terminal run or **Stop program** in the control panel
sends stop commands to the cobot before ending the run.

Before `main.py` or a control-panel run can start, the actual joints must be
within 0.005 rad of the taught joint-only `Home` waypoint. A maximum-displacement
measurement failure returns from the low pose to the high plane, translates
back to `p_start_h`, reports the failed line index and position, and stops the
sequence without running the end routine.

Its sequence is:

```text
start routine -> force measurements along the line -> end routine
```

## Active folders

- `src/program`: complete program entry point.
- `src/robot`: robot communication, movements, URScript generation, and routines.
- `src/measurement`: measurement-line traversal and the force procedure.
- `src/routines`: creates files in `routine_files` from robot exports stored in
  `polyscope_scripts`.
- `examples`: focused movement, routine, and hardcoded-program examples.
- `old`: archived experiments and replaced implementations.

The optional placeholder acquisition implementation is self-contained in
`data_acquisition_server` and is not used by `main.py`.

## Routine data

Generate the active routines file from the PolyScope script with:

```powershell
python src\routines\create_routines_file.py
```

The complete procedure is documented in `src/routines/read_me_routines.md`.
The retained examples are:

```powershell
python examples\go_to_waypoint.py
python examples\run_single_routine.py
python examples\run_hardcoded_program.py
python examples\run_hardcoded_measurements.py
```

`run_hardcoded_program.py` performs the same start-routine, measurement, and
end-routine sequence as `main.py`, but keeps all operator parameters directly
in the Python file so it can be launched using an editor's Run button.

`run_hardcoded_measurements.py` runs only the measurement traversal with
parameters stored in that file. It requires the robot to be at `p_start_h`,
checks that position before moving, and finishes at the high end-of-line pose.

## Measurement files

Measurement settings are in `src/program/config/config.json`. The
active force implementation is:

```text
src/measurement/apply_force.py
src/measurement/polyscope_scripts/apply_force_logic.script
```

The controller-side program path is configured as
`Benoit/apply_force.urp`. The robot must be in Remote Control mode, powered on,
and brake-released (`RUNNING`) before a routine, waypoint move, or measurement
can start.

Routine motion is configured per step in `routines_block.json` with `type`
(`j` or `l`), `acceleration`, `speed`, and `blend_radius`. General measurement
motion uses the equivalent `motion` dictionary in `config.json`. The force
approach, return motion, and force-mode stop deceleration remain hardcoded
inside the controller-side force script.
