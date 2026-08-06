"""Launch only the force approach from the current robot position."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEASUREMENT_DIR = PROJECT_ROOT / "Code" / "Measurement"
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"

for folder in [MEASUREMENT_DIR, ROBOT_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from python_step_force_approach import launch_force_approach
from measurement_config import read_measurement_config
from robot_connection import assert_remote_control, get_rtde_receive


ROBOT_IP = "192.168.3.10"
MEASUREMENT_CONFIG_FILE = PROJECT_ROOT / "Configuration" / "measurement_config.json"


if __name__ == "__main__":
    config = read_measurement_config(MEASUREMENT_CONFIG_FILE, verbose=True)

    input("Press Enter to launch force approach from the current position, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    try:
        success = launch_force_approach(ROBOT_IP, rtde_receive, config)
        print(f"force_approach_success={success}")
    finally:
        rtde_receive.disconnect()
