"""Launch only the force approach URP and wait for its socket result."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEASUREMENT_DIR = PROJECT_ROOT / "Code" / "Measurement"
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"

for folder in [MEASUREMENT_DIR, ROBOT_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from force_approach_urp import launch_force_approach_urp
from measurement_config import read_measurement_config
from robot_connection import assert_remote_control


ROBOT_IP = "192.168.3.10"
MEASUREMENT_CONFIG_FILE = PROJECT_ROOT / "Configuration" / "measurement_config.json"


if __name__ == "__main__":
    config = read_measurement_config(MEASUREMENT_CONFIG_FILE, verbose=True)
    program_name = config["force_approach_urp"]["program_name"]

    input(f"Press Enter to launch URP '{program_name}', or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)

    success = launch_force_approach_urp(ROBOT_IP, config)
    print(f"force_approach_success={success}")
