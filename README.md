# UR15 Cobot Control

The active program is:

```powershell
python src\program\main.py
```

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
- `examples`: one-waypoint movement and one-routine execution.
- `old`: archived experiments and replaced implementations.

The optional placeholder acquisition implementation is self-contained in
`data_acquisition_server` and is not used by `main.py`.

## Routine data

Generate the active routines file from the PolyScope script with:

```powershell
python src\routines\create_routines_file.py
```

The complete procedure is documented in `src/routines/read_me_routines.md`.
The two retained examples are:

```powershell
python examples\go_to_waypoint.py
python examples\run_single_routine.py
```

## Measurement files

Measurement settings are in `src/program/config/config.json`. The
active force implementation is:

```text
src/measurement/apply_force.py
src/measurement/polyscope_scripts/apply_force_logic.script
```

The controller-side program path is configured as
`Benoit/apply_force.urp`. The robot must be in Remote Control mode.
