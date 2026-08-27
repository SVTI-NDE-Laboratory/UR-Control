"""Create an example routines JSON file from a PolyScope script export.

Edit the paths, waypoint order, and motion parameters below, then run this
file. It writes ``examples/generated_routines.json`` by default so the active
robot configuration is not overwritten accidentally.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
if str(ROUTINES_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINES_DIR))

from create_routines_file import create_routines_file


# ---------------------------------------------------------------------------
# Review these hard-coded values before running the example.
# ---------------------------------------------------------------------------

SCRIPT_PATH = (
    ROUTINES_DIR
    / "polyscope_scripts"
    / "Define_Waypoints_PK-03-PRISM-A.script"
)

# Inspect this generated file before changing the path to routines_block.json.
OUTPUT_PATH = PROJECT_ROOT / "src" / "routines" / "routine_files" / "routines_pk-03-prism-a.json"

START_WAYPOINTS = ["Home", "Tmp1", "Tmp2", "p_start_h"]
END_WAYPOINTS = list(reversed(START_WAYPOINTS))

# These are stored for point-to-point planning even though they are not routine
# steps. Their names must match the taught labels in the PolyScope script.
MEASUREMENT_WAYPOINTS = ["p_start_l", "p_end_l", "p_end_h"]

# Joint speed/acceleration use rad/s and rad/s^2. Linear speed/acceleration
# use mm/s and mm/s^2. All blend radii use mm.
HOME_MOTION = {
    "type": "j",
    "acceleration": 0.2,
    "speed": 4.0,
    "blend_radius": 0.0,
}
INTERMEDIATE_MOTION = {
    "type": "j",
    "acceleration": 1.0,
    "speed": 10.0,
    "blend_radius": 20.0,
}
STOPPED_JOINT_MOTION = {
    "type": "j",
    "acceleration": 1.0,
    "speed": 10.0,
    "blend_radius": 0.0,
}
LEAVE_MEASUREMENT_LINE_MOTION = {
    "type": "l",
    "acceleration": 200.0,
    "speed": 250.0,
    "blend_radius": 0.0,
}


def make_steps(names: list[str], first_motion: dict, last_motion: dict) -> list[dict]:
    """Build routine steps with no blending at either endpoint."""

    steps = [
        {"waypoint": name, "motion": dict(INTERMEDIATE_MOTION)}
        for name in names
    ]
    steps[0]["motion"] = dict(first_motion)
    steps[-1]["motion"] = dict(last_motion)
    return steps


def run() -> None:
    """Extract taught waypoints and write the example routines file."""

    routines = [
        {
            "name": "start",
            "steps": make_steps(
                START_WAYPOINTS,
                HOME_MOTION,
                STOPPED_JOINT_MOTION,
            ),
        },
        {
            "name": "end",
            "steps": make_steps(
                END_WAYPOINTS,
                LEAVE_MEASUREMENT_LINE_MOTION,
                STOPPED_JOINT_MOTION,
            ),
        },
    ]

    missing = create_routines_file(
        SCRIPT_PATH,
        OUTPUT_PATH,
        routines,
        additional_waypoint_names=MEASUREMENT_WAYPOINTS,
    )
    if missing:
        raise SystemExit(
            "The file was created, but these waypoint definitions are missing: "
            + ", ".join(missing)
        )

    print("All routine and measurement waypoints were extracted successfully.")


if __name__ == "__main__":
    run()
