"""Create `routines.json` from a URScript waypoint file.

The file created has two top-level sections:

- `waypoints`: one entry per waypoint used by any routine, with `p` and/or `q`.
- `routines`: named sequences that reference waypoints by name.

Example output:

```json
{
  "waypoints": {
    "Home": {"q": [...]},
    "Tmp1": {"p": [...], "q": [...]}
  },
  "routines": [
    {"name": "start", "order": ["Home", "Tmp2", "Tmp1"]},
    {"name": "end", "order": ["Tmp1", "Tmp2", "Home"]}
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
        for name in routine["order"]:
            if name not in names:
                names.append(name)
    return names


def create_routines_file(
    script_path: str | Path,
    output_path: str | Path,
    routines: list[dict],
) -> list[str]:
    """Read waypoint values and create a routines JSON file.

    Args:
        script_path: PolyScope `.script` file containing waypoint definitions.
        output_path: JSON file to create.
        routines: List of routines. Each routine must have:
            - `name`: routine name.
            - `order`: waypoint names in movement order.

    Returns:
        Names of waypoints that were referenced by routines but not found in
        the script file.
    """

    script_path = Path(script_path)
    output_path = Path(output_path)

    waypoint_names = unique_waypoint_names(routines)
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
    script_path = PROJECT_ROOT / "Configuration" / "paths_Stefan.script"
    output_path = PROJECT_ROOT / "Configuration" / "routines.json"
    
    # Define routines with waypoint names in movement order
    start_order = ["Home", "Tmp1", "Tmp2", "p_start_h"]
    end_order = list(reversed(start_order))

    routines = [
        {"name": "start", "order": start_order},
        {"name": "end", "order": end_order},
    ]

    # Create routines file
    create_routines_file(script_path, output_path, routines)
