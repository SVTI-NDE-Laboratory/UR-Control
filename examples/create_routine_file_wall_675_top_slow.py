"""Create the slow wall routine file from the Define_Points_Wall export."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
if str(ROUTINES_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINES_DIR))

from create_routines_file import create_routines_file


SCRIPT_PATH = ROUTINES_DIR / "polyscope_scripts" / "Define_Points_Wall.script"
OUTPUT_PATH = (
    ROUTINES_DIR
    / "routine_files"
    / "routines_wall_675_top_slow.json"
)

HOME_TO_START_WAYPOINTS = [
    "Home",
    "home_to_start1",
    "home_to_start2",
    "p_start_h",
]
START_TO_HOME_WAYPOINTS = list(reversed(HOME_TO_START_WAYPOINTS))

END_TO_HOME_WAYPOINTS = [
    "p_end_h",
    "end_to_home1",
    "end_to_home2",
    "end_to_home3",
    "Home",
]
HOME_TO_END_WAYPOINTS = list(reversed(END_TO_HOME_WAYPOINTS))

MEASUREMENT_WAYPOINTS = ["p_start_l", "p_end_l"]

# Joint acceleration uses rad/s^2, speed uses rad/s, and blend radius uses mm.
# Keep every step slow and unblended until the wall path has been verified.
SLOW_JOINT_MOTION = {
    "type": "j",
    "acceleration": 0.1,
    "speed": 0.5,
    "blend_radius": 0.0,
}


def make_joint_steps(names: list[str]) -> list[dict]:
    """Return slow movej steps for every waypoint name."""

    return [
        {
            "waypoint": name,
            "motion": dict(SLOW_JOINT_MOTION),
        }
        for name in names
    ]


def run() -> None:
    """Extract all wall waypoints and write the routine JSON file."""

    routines = [
        {
            "name": "home_to_start",
            "steps": make_joint_steps(HOME_TO_START_WAYPOINTS),
        },
        {
            "name": "start_to_home",
            "steps": make_joint_steps(START_TO_HOME_WAYPOINTS),
        },
        {
            "name": "home_to_end",
            "steps": make_joint_steps(HOME_TO_END_WAYPOINTS),
        },
        {
            "name": "end_to_home",
            "steps": make_joint_steps(END_TO_HOME_WAYPOINTS),
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

    print(f"Created {OUTPUT_PATH}")


if __name__ == "__main__":
    run()
