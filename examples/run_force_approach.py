"""Run one force approach from the robot's current TCP pose.

Open this file in an editor and press Run. The controller-side force program
captures the current TCP pose, approaches along its tool Z+ axis, then returns
to the captured pose. Review every hard-coded parameter before use.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"

for folder in [MEASUREMENT_DIR, ROBOT_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from apply_force import apply_force
from robot_connection import stop_robot


# ---------------------------------------------------------------------------
# Review these hard-coded parameters before running the example.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
PROGRAM_PATH = "/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp"

# Distances are millimetres and forces are newtons. The approach direction is the
# tool Z+ axis at the pose where the controller-side program starts.
MAX_DISTANCE = 50.0
TARGET_FORCE = 20.0
SIMULATION = True

# Keep this enabled to prevent an editor Run click from moving the robot.
REQUIRE_OPERATOR_CONFIRMATION = True


def run() -> None:
    """Approach from the current pose, hold briefly, and return to that pose."""

    if REQUIRE_OPERATOR_CONFIRMATION:
        input(
            "Confirm the tool Z+ approach path is clear, then press Enter to "
            "start the force approach, or Ctrl+C to cancel."
        )

    try:
        force_reached, _ = apply_force(
            ROBOT_IP,
            PROGRAM_PATH,
            MAX_DISTANCE,
            TARGET_FORCE,
            simulation=SIMULATION,
            simulation_program_path=PROGRAM_PATH.rsplit("/", 1)[0] + "/apply_force_simulation.urp",
        )
    except KeyboardInterrupt:
        stop_robot(ROBOT_IP)
        print("\nForce approach cancelled; a robot stop was requested.")
        raise SystemExit(130)

    if force_reached:
        print("Force threshold reached; robot returned to its starting pose.")
    else:
        print("Force was not reached before the distance/time limit; robot returned to its starting pose.")


if __name__ == "__main__":
    run()
