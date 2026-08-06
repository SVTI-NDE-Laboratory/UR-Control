"""Run named routines from `Configuration/routines.json`."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTINE_DATA_DIR = PROJECT_ROOT / "Code" / "RoutineData"
if str(ROUTINE_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINE_DATA_DIR))

from robot_move import joint_degrees, movej, movel_pose
from robot_scripts import ur_pose
from read_routines import get_routine, get_waypoint, read_routines_file
from robot_connection import assert_remote_control, get_rtde_receive


ROUTINES_FILE = PROJECT_ROOT / "Configuration" / "routines.json"
ROBOT_IP = "192.168.3.10"

A = 0.05
V = 1.0
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0


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

    Each waypoint is executed as one movej. Verbose mode prints one line per move.
    """

    routine = get_routine(routines_data, routine_name)

    if verbose:
        print(f"Routine: {routine_name}")

    # Loop through all waypoints in given routine
    for index, waypoint_name in enumerate(routine["order"]):

        waypoint = get_waypoint(routines_data, waypoint_name)
        use_linear_move = linear_first_waypoint and index == 0

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


if __name__ == "__main__":
    routines_file = ROUTINES_FILE
    robot_ip = ROBOT_IP

    routines_data = read_routines_file(routines_file)

    input("Press Enter to connect and run the start routine, or Ctrl+C to cancel.")
    assert_remote_control(robot_ip)
    rtde_receive = get_rtde_receive(robot_ip)

    run_routine(
        routine_name="start",
        routines_data=routines_data,
        robot_ip=robot_ip,
        rtde_receive=rtde_receive,
        a=A,
        v=V,
        joint_tolerance=JOINT_TOLERANCE,
        wait_timeout=WAIT_TIMEOUT,
        confirm_each_step=False,
        verbose=True,
        linear_first_waypoint=False,
    )

    rtde_receive.disconnect()
