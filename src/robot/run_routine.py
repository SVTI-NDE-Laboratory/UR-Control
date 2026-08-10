"""Run named routines from a loaded routines file."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
if str(ROUTINES_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINES_DIR))

from robot_move import joint_degrees, movej, movel_pose
from robot_scripts import ur_pose
from read_routines import get_routine, get_waypoint


def run_routine(
    routine_name: str,
    routines_data: dict,
    robot_ip: str,
    rtde_receive,
    a: float,
    v: float,
    joint_tolerance: float,
    wait_timeout: float,
    confirm_each_step: bool,
    verbose: bool,
    linear_first_waypoint: bool = False,
) -> None:
    """Run a named routine from loaded routine data.

    Waypoints normally use movej. The first waypoint may use movel when
    requested, except joint-only Home, which always uses movej.
    """

    routine = get_routine(routines_data, routine_name)

    if verbose:
        print(f"Routine: {routine_name}")

    # Loop through all waypoints in given routine
    for index, waypoint_name in enumerate(routine["order"]):

        waypoint = get_waypoint(routines_data, waypoint_name)
        use_linear_move = linear_first_waypoint and index == 0

        # Home is extracted as a joint target only, so it cannot use movel.
        if use_linear_move and waypoint_name == "Home" and "p" not in waypoint:
            use_linear_move = False

        if use_linear_move:
            if "p" not in waypoint:
                raise ValueError(f"Waypoint '{waypoint_name}' has no p target for linear return.")
            if verbose:
                print(f"Moving to {waypoint_name}. Target: {ur_pose(waypoint['p'])} linear")
            movel_pose(robot_ip, rtde_receive, waypoint["p"], a, v, wait_timeout)
        else:
            if "q" not in waypoint:
                raise ValueError(f"Waypoint '{waypoint_name}' has no q target for movej.")
            q_target = waypoint["q"]
            if verbose:
                print(f"Moving to {waypoint_name}. Target: {joint_degrees(q_target)}")
            movej(robot_ip, rtde_receive, q_target, a, v, joint_tolerance, wait_timeout)

        if confirm_each_step:
            input("Confirm position, then press Enter for the next move.")
