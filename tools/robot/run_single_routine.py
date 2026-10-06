"""Run one routine as a recovery or manual-positioning script."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from read_routines import get_routine, get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_robot_running,
    assert_robot_safe,
    get_rtde_receive,
)
from robot_move import max_joint_error
from run_routine import run_routine


ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routine_mira.json"

ROUTINE_NAME = "start_to_home"
JOINT_TOLERANCE = 0.01

WAIT_TIMEOUT = 30.0


def assert_at_routine_first_waypoint(
    rtde_receive,
    routines_data: dict,
    routine_name: str,
    joint_tolerance: float,
) -> str:
    """Require the robot to already be at the routine's first waypoint."""

    routine = get_routine(routines_data, routine_name)
    if not routine["steps"]:
        raise ValueError(f"Routine '{routine_name}' has no steps.")

    first_waypoint_name = routine["steps"][0]["waypoint"]
    first_waypoint = get_waypoint(routines_data, first_waypoint_name)
    if "q" not in first_waypoint:
        raise ValueError(
            f"Routine '{routine_name}' first waypoint '{first_waypoint_name}' "
            "has no joint target for startup verification."
        )

    assert_robot_safe(rtde_receive)
    actual_q = rtde_receive.getActualQ()
    target_q = first_waypoint["q"]
    if len(actual_q) != len(target_q):
        raise UnsafeStartPositionError(
            f"Cannot verify routine '{routine_name}' first waypoint "
            f"'{first_waypoint_name}': robot and target joint vectors have "
            "different lengths."
        )

    joint_errors = [abs(actual - target) for actual, target in zip(actual_q, target_q)]
    maximum_error = max_joint_error(actual_q, target_q)
    if maximum_error > joint_tolerance:
        joint_number = joint_errors.index(maximum_error) + 1
        raise UnsafeStartPositionError(
            f"Unsafe routine start prevented: robot is not at the first waypoint "
            f"'{first_waypoint_name}' for routine '{routine_name}'. "
            f"Joint {joint_number} differs by {maximum_error:.4f} rad; "
            f"allowed difference is {joint_tolerance:.4f} rad."
        )

    return first_waypoint_name


if __name__ == "__main__":

    routines_data = read_routines_file(ROUTINES_FILE)

    input(f"Press Enter to connect and run routine '{ROUTINE_NAME}', or Ctrl+C to cancel.")
    assert_robot_running(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    try:
        first_waypoint_name = assert_at_routine_first_waypoint(
            rtde_receive,
            routines_data,
            ROUTINE_NAME,
            JOINT_TOLERANCE,
        )
        print(
            f"Startup position verified: robot is at the first waypoint "
            f"'{first_waypoint_name}'."
        )

        run_routine(
            routine_name=ROUTINE_NAME,
            routines_data=routines_data,
            robot_ip=ROBOT_IP,
            rtde_receive=rtde_receive,
            joint_tolerance=JOINT_TOLERANCE,
            wait_timeout=WAIT_TIMEOUT,
            confirm_each_step=False,
            verbose=True,
        )
    finally:
        rtde_receive.disconnect()
