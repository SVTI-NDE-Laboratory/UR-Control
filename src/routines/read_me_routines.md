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

- `script_path` to the raw wall `.script` filename.
- `home_to_start_waypoints` to the waypoint order used to approach
  `p_start_h`.
- `end_to_home_waypoints` to the waypoint order used to return from `p_end_h`.
- `wall_joint_motion` to the desired joint speed, acceleration, and
  intermediate blend radius.

Each name in these lists must match a waypoint label in the PolyScope script.
Point-to-point measurement waypoints do not need to appear as routine steps.
Pass their names through `additional_waypoint_names` so their Cartesian poses
are also stored in the generated routines file.
Each generated routine step contains:

```json
{
  "waypoint": "Tmp1",
  "motion": {
    "type": "j",
    "acceleration": 0.4,
    "speed": 2.0,
    "blend_radius": 5.0
  }
}
```

For type `j`, acceleration and speed use `rad/s^2` and `rad/s`. For type `l`,
they use `mm/s^2` and `mm/s`.

`blend_radius` is stored in millimetres. Routine steps are sent
to the controller as one program, so nonzero radii on intermediate steps blend
into the following move. The final step must use `0.0` so completion can be
verified at its exact target. The generator also keeps the first step at
`0.0`, so each route starts from an exact point.

## 3. Generate the JSON file

From the project root, run:

```powershell
python src\routines\create_routines_file.py
```

The generated file is written to:

```text
src/routines/routine_files/routines_wall_275_top.json
```

The script reports any requested waypoint it cannot find. Resolve all missing
waypoints before moving the robot.

## 4. Use the routines

`main.py`, `go_to_waypoint.py`, and `run_single_routine.py` all read the
configured JSON file from `routine_files`. Regenerate it whenever waypoint
positions, routine orders, or routine motion settings change.

For a standalone example that writes a non-active output file, run:

```powershell
python examples\create_routines.py
```
