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
- `intermediate_joint_motion` to the desired motion between the endpoints.
- `conservative_joint_motion` for departure from Home and
  `conservative_linear_motion` for the end routine's departure from
  `p_start_h`.
- `end_joint_motion` for the final moves to `p_start_h` and Home. Its blend
  radius must remain zero.

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
    "acceleration": 0.2,
    "speed": 4.0,
    "blend_radius": 0.0
  }
}
```

For type `j`, acceleration and speed use `rad/s^2` and `rad/s`. For type `l`,
they use `m/s^2` and `m/s`.

`blend_radius` is the URScript `r` parameter in metres. Routine steps are sent
to the controller as one program, so nonzero radii on intermediate steps blend
into the following move. The final step must use `0.0` so completion can be
verified at its exact target. `confirm_each_step` also requires zero radii.

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
positions, routine orders, or routine motion settings change.

For a standalone example that writes a non-active output file, run:

```powershell
python examples\create_routines.py
```
