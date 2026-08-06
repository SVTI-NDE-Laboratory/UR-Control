"""Run one routine as a recovery or manual-positioning script."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
ROUTINE_DATA_DIR = PROJECT_ROOT / "Code" / "RoutineData"

for folder in [ROBOT_DIR, ROUTINE_DATA_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from read_routines import read_routines_file
from robot_connection import assert_remote_control, get_rtde_receive
from run_routine import run_routine


ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = PROJECT_ROOT / "Configuration" / "routines.json"

ROUTINE_NAME = "end"
LINEAR_FIRST_WAYPOINT = True

A = 0.2
V = 4
JOINT_TOLERANCE = 0.01

WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    routines_data = read_routines_file(ROUTINES_FILE)

    input(f"Press Enter to connect and run routine '{ROUTINE_NAME}', or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    run_routine(
        routine_name=ROUTINE_NAME,
        routines_data=routines_data,
        robot_ip=ROBOT_IP,
        rtde_receive=rtde_receive,
        a=A,
        v=V,
        joint_tolerance=JOINT_TOLERANCE,
        wait_timeout=WAIT_TIMEOUT,
        confirm_each_step=False,
        verbose=True,
        linear_first_waypoint=LINEAR_FIRST_WAYPOINT,
    )

    rtde_receive.disconnect()
