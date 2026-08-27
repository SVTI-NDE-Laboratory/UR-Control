"""Move directly to one waypoint from the active routines file."""

import math
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from robot_move import joint_degrees, movej, movel_pose, tcp_target_errors
from robot_scripts import ur_pose
from read_routines import read_waypoint
from robot_connection import assert_robot_running, get_rtde_receive


MM_PER_METRE = 1000.0
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_wall_675_top_slow.json"

WAYPOINT_NAME = "Home"
USE_LINEAR_MOVE = False  # Set to False to use movej instead of movel

LINEAR_ACCELERATION = 100.0
LINEAR_SPEED = 50.0
JOINT_ACCELERATION = 0.1
JOINT_SPEED = 0.05
JOINT_TOLERANCE = 0.005
WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    waypoint = read_waypoint(ROUTINES_FILE, WAYPOINT_NAME)

    input(f"Press Enter to connect and move to '{WAYPOINT_NAME}', or Ctrl+C to cancel.")
    assert_robot_running(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    if USE_LINEAR_MOVE:
        if "p" not in waypoint:
            raise ValueError(f"Waypoint '{WAYPOINT_NAME}' has no p target for linear move.")
        print(f"Moving to {WAYPOINT_NAME}. Target: {ur_pose(waypoint['p'])} linear")
        movel_pose(
            ROBOT_IP,
            rtde_receive,
            waypoint["p"],
            LINEAR_ACCELERATION / MM_PER_METRE,
            LINEAR_SPEED / MM_PER_METRE,
            WAIT_TIMEOUT,
        )
        position_error, rotation_error = tcp_target_errors(
            rtde_receive.getActualTCPPose(), waypoint["p"]
        )
        print(
            f"Waypoint '{WAYPOINT_NAME}' reached and settled. "
            f"Position error: {position_error * 1000:.3f} mm; "
            f"rotation-vector error: {rotation_error:.6f} rad."
        )
    else:
        if "q" not in waypoint:
            raise ValueError(f"Waypoint '{WAYPOINT_NAME}' has no q target for movej.")
        print(f"Moving to {WAYPOINT_NAME}. Target: {joint_degrees(waypoint['q'])}")
        movej(
            ROBOT_IP,
            rtde_receive,
            waypoint["q"],
            JOINT_ACCELERATION,
            JOINT_SPEED,
            JOINT_TOLERANCE,
            WAIT_TIMEOUT,
        )
        final_error = max(
            abs(actual - target)
            for actual, target in zip(rtde_receive.getActualQ(), waypoint["q"])
        )
        print(
            f"Waypoint '{WAYPOINT_NAME}' reached and settled. "
            f"Maximum joint error: {final_error:.6f} rad "
            f"({math.degrees(final_error):.3f} deg)."
        )

    rtde_receive.disconnect()
