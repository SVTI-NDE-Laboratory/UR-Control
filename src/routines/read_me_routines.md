# Creating a routines file

The routine tools convert waypoint definitions exported by PolyScope into the
JSON file used by `main.py`.

## 1. Export the robot program

Export or copy the PolyScope `.script` file containing the required waypoint
definitions into:

```text
src/routines/polyscope_scripts
```

The extractor reads the
waypoint poses and joint positions from this text-based script; it does not
extract a binary `.urp` file directly.

## 2. Define the routines

Open `create_routines_file.py` and set:

- `script_path` to the raw `.script` filename.
- `start_order` to the waypoint order used to approach the measurement line.
- `end_order` to the waypoint order used to return from the line.

Each name in these lists must match a waypoint label in the PolyScope script.

## 3. Generate the JSON file

From the project root, run:

```powershell
python src\routines\create_routines_file.py
```

The generated file is written to:

```text
src/routines/routine_files/routines_block.json
```

The script reports any requested waypoint it cannot find. Resolve all missing
waypoints before moving the robot.

## 4. Use the routines

`main.py`, `go_to_waypoint.py`, and `run_single_routine.py` all read the
configured JSON file from `routine_files`. Regenerate it whenever waypoint
positions or routine orders change.
