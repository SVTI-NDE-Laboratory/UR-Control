"""Create `routines.json` from a URScript waypoint file.

The file created has two top-level sections:

- `waypoints`: one entry per waypoint used by any routine, with `p` and/or `q`.
- `routines`: named sequences with one motion configuration per waypoint.

Example output:

```json
{
  "waypoints": {
    "Home": {"q": [...]},
    "Tmp1": {"p": [...], "q": [...]}
  },
  "routines": [
    {"name": "start", "steps": [
      {"waypoint": "Home", "motion": {"type": "j", "acceleration": 0.2,
       "speed": 4.0, "blend_radius": 0.0}}
    ]}
  ]
}
```
"""

from pathlib import Path
import json

from extract_waypoints_from_script import extract_waypoints_from_script


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def unique_waypoint_names(routines: list[dict]) -> list[str]:
    """Return waypoint names used by `routines`, preserving first occurrence.

    This avoids storing duplicate waypoint data in the generated JSON.
    """

    names = []
    for routine in routines:
        for step in routine["steps"]:
            name = step["waypoint"]
            if name not in names:
                names.append(name)
    return names


def create_routines_file(
    script_path: str | Path,
    output_path: str | Path,
    routines: list[dict],
    additional_waypoint_names: list[str] | None = None,
) -> list[str]:
    """Read waypoint values and create a routines JSON file.

    Args:
        script_path: PolyScope `.script` file containing waypoint definitions.
        output_path: JSON file to create.
        routines: List of routines. Each routine must have:
            - `name`: routine name.
            - `steps`: ordered dictionaries containing `waypoint` and `motion`.
        additional_waypoint_names: Waypoints to store even though they are not
            routine steps, such as measurement-line endpoints.

    Returns:
        Names of waypoints that were referenced by routines but not found in
        the script file.
    """

    script_path = Path(script_path)
    output_path = Path(output_path)

    waypoint_names = unique_waypoint_names(routines)
    for name in additional_waypoint_names or []:
        if name not in waypoint_names:
            waypoint_names.append(name)
    waypoints = extract_waypoints_from_script(script_path, waypoint_names)
    missing = [name for name, data in waypoints.items() if not data]

    if missing:
        print(f"Waypoint(s) not found in {script_path}: {missing}")

    found_waypoints = {
        name: data
        for name, data in waypoints.items()
        if data
    }

    payload = {
        "waypoints": found_waypoints,
        "routines": routines,
    }

    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")

    return missing


if __name__ == "__main__":
    # Define script and output paths
    routines_dir = PROJECT_ROOT / "src" / "routines"
    script_path = routines_dir / "polyscope_scripts" / "Define_Waypoints_Block.script"
    output_path = routines_dir / "routine_files" / "routines_block.json"
    
    # Define routines and the motion used to reach each waypoint. Joint speed
    # and acceleration use rad/s and rad/s^2. Linear speed and acceleration
    # use mm/s and mm/s^2. All blend radii use mm.
    start_order = ["Home", "Tmp1", "Tmp2", "p_start_h"]
    end_order = list(reversed(start_order))

    intermediate_joint_motion = {
        "type": "j",
        "acceleration": 1.0,
        "speed": 10.0,
        "blend_radius": 20.0,
    }
    conservative_joint_motion = {
        "type": "j",
        "acceleration": 0.2,
        "speed": 4.0,
        "blend_radius": 0.0,
    }
    conservative_linear_motion = {
        "type": "l",
        "acceleration": 200.0,
        "speed": 250.0,
        "blend_radius": 0.0,
    }
    end_joint_motion = {
        "type": "j",
        "acceleration": 1.0,
        "speed": 10.0,
        "blend_radius": 0.0,
    }

    start_steps = [
        {"waypoint": name, "motion": dict(intermediate_joint_motion)}
        for name in start_order
    ]
    end_steps = [
        {
            "waypoint": name,
            "motion": dict(
                conservative_linear_motion
                if index == 0
                else intermediate_joint_motion
            ),
        }
        for index, name in enumerate(end_order)
    ]

    # Departure from Home and the linear departure from p_start_h use the
    # conservative settings. Intermediate waypoints may blend. Both routine
    # endpoints use the intermediate joint speed but must stop exactly.
    start_steps[0]["motion"] = dict(conservative_joint_motion)
    start_steps[-1]["motion"] = dict(end_joint_motion)
    end_steps[-1]["motion"] = dict(end_joint_motion)

    routines = [
        {"name": "start", "steps": start_steps},
        {"name": "end", "steps": end_steps},
    ]

    # Create routines file
    create_routines_file(
        script_path,
        output_path,
        routines,
        additional_waypoint_names=["p_start_l", "p_end_l", "p_end_h"],
    )
