"""Read routine definition files.

The routine file format is:

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

import json
from pathlib import Path


def read_routines_file(path: str | Path) -> dict:
    """Read a routines JSON file.

    The returned dict contains top-level `waypoints` and `routines` sections.
    """

    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_routine(path: str | Path, routine_name: str) -> dict:
    """Read one named routine directly from a routines JSON file.

    Use this when the caller only needs one routine and has not loaded the file.
    """

    routines_data = read_routines_file(path)
    return get_routine(routines_data, routine_name)


def read_waypoint(path: str | Path, waypoint_name: str) -> dict:
    """Read one named waypoint directly from a routines JSON file.

    Use this for simple scripts that only need a single robot target.
    """

    routines_data = read_routines_file(path)
    return get_waypoint(routines_data, waypoint_name)


def read_waypoints(path: str | Path, waypoint_names: list[str]) -> dict:
    """Read several named waypoints directly from a routines JSON file.

    The returned dictionary is keyed by waypoint name.
    """

    routines_data = read_routines_file(path)
    return {name: get_waypoint(routines_data, name) for name in waypoint_names}


def get_routine(routines_data: dict, routine_name: str) -> dict:
    """Return the routine with `routine_name`.

    Raises a clear error listing available routine names if it is missing.
    """

    for routine in routines_data["routines"]:
        if routine["name"] == routine_name:
            return routine

    available = [routine["name"] for routine in routines_data["routines"]]
    raise ValueError(f"Routine '{routine_name}' not found. Available routines: {available}")


def get_waypoint(routines_data: dict, waypoint_name: str) -> dict:
    """Return the waypoint with `waypoint_name`.

    A waypoint may contain `q`, `p`, or both depending on the source script.
    """

    try:
        return routines_data["waypoints"][waypoint_name]
    except KeyError as error:
        raise ValueError(f"Waypoint '{waypoint_name}' is not defined.") from error
