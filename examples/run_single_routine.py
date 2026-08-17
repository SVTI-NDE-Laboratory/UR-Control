"""Run one routine as a recovery or manual-positioning script."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from read_routines import read_routines_file
from robot_connection import assert_robot_running, get_rtde_receive
from run_routine import run_routine


ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block_diagonal.json"

ROUTINE_NAME = "end"
JOINT_TOLERANCE = 0.01

WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    routines_data = read_routines_file(ROUTINES_FILE)

    input(f"Press Enter to connect and run routine '{ROUTINE_NAME}', or Ctrl+C to cancel.")
    assert_robot_running(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

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

    rtde_receive.disconnect()
