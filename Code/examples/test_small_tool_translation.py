"""Test one small tool-frame translation without force logic."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import assert_remote_control, get_rtde_receive
from robot_move import translate_tool


ROBOT_IP = "192.168.3.10"
OFFSET = [0.0, 0.0, 0.001]
A = 0.05
V = 0.05
TIMEOUT = 5.0


if __name__ == "__main__":
    input(f"Press Enter to move by tool offset {OFFSET}, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    try:
        before = rtde_receive.getActualTCPPose()
        translate_tool(ROBOT_IP, rtde_receive, OFFSET, A, V, TIMEOUT)
        after = rtde_receive.getActualTCPPose()
        print(f"Before: {before}")
        print(f"After:  {after}")
    finally:
        rtde_receive.disconnect()
