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
    routines_dir = PROJECT_ROOT / "src" / "routines"
    script_path = routines_dir / "polyscope_scripts" / "Define_Points_Wall_90deg.script"
    output_path = routines_dir / "routine_files" / "routines_wall_275_top.json"

    home_to_start_waypoints = [
        "Home",
        "home_to_start1",
        "home_to_start2",
        "p_start_h",
    ]
    start_to_home_waypoints = list(reversed(home_to_start_waypoints))

    end_to_home_waypoints = [
        "p_end_h",
        "end_to_home1",
        "end_to_home2",
        "end_to_home3",
        "Home",
    ]
    home_to_end_waypoints = list(reversed(end_to_home_waypoints))

    # Joint acceleration uses rad/s^2, speed uses rad/s, and blend radius uses
    # mm. Intermediate waypoints use a small blend radius for smoother travel.
    wall_joint_motion = {
        "type": "j",
        "acceleration": 0.4,
        "speed": 2.0,
        "blend_radius": 5.0,
    }
    stopped_wall_joint_motion = {
        **wall_joint_motion,
        "blend_radius": 0.0,
    }

    def make_joint_steps(names: list[str]) -> list[dict]:
        steps = [
            {
                "waypoint": name,
                "motion": dict(wall_joint_motion),
            }
            for name in names
        ]
        steps[0]["motion"] = dict(stopped_wall_joint_motion)
        steps[-1]["motion"] = dict(stopped_wall_joint_motion)
        return steps

    routines = [
        {
            "name": "home_to_start",
            "steps": make_joint_steps(home_to_start_waypoints),
        },
        {
            "name": "start_to_home",
            "steps": make_joint_steps(start_to_home_waypoints),
        },
        {
            "name": "home_to_end",
            "steps": make_joint_steps(home_to_end_waypoints),
        },
        {
            "name": "end_to_home",
            "steps": make_joint_steps(end_to_home_waypoints),
        },
    ]

    missing = create_routines_file(
        script_path,
        output_path,
        routines,
        additional_waypoint_names=["p_start_l", "p_end_l"],
    )
    if missing:
        raise SystemExit(
            "The file was created, but these waypoint definitions are missing: "
            + ", ".join(missing)
        )
