"""Move directly to one waypoint from the active routines file."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from robot_move import joint_degrees, movej, movel_pose
from robot_scripts import ur_pose
from read_routines import read_waypoint
from robot_connection import assert_remote_control, get_rtde_receive


ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines.json"

WAYPOINT_NAME = "Home"
USE_LINEAR_MOVE = False

A = 0.2
V = 4
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    waypoint = read_waypoint(ROUTINES_FILE, WAYPOINT_NAME)

    input(f"Press Enter to connect and move to '{WAYPOINT_NAME}', or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    if USE_LINEAR_MOVE:
        if "p" not in waypoint:
            raise ValueError(f"Waypoint '{WAYPOINT_NAME}' has no p target for linear move.")
        print(f"Moving to {WAYPOINT_NAME}. Target: {ur_pose(waypoint['p'])} linear")
        movel_pose(ROBOT_IP, rtde_receive, waypoint["p"], A, V, WAIT_TIMEOUT)
    else:
        if "q" not in waypoint:
            raise ValueError(f"Waypoint '{WAYPOINT_NAME}' has no q target for movej.")
        print(f"Moving to {WAYPOINT_NAME}. Target: {joint_degrees(waypoint['q'])}")
        movej(ROBOT_IP, rtde_receive, waypoint["q"], A, V, JOINT_TOLERANCE, WAIT_TIMEOUT)

    rtde_receive.disconnect()
