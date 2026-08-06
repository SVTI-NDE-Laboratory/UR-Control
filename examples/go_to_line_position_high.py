"""Move to a configured line position while staying in high mode."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEASUREMENT_DIR = PROJECT_ROOT / "Code" / "Measurement"
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"

for folder in [MEASUREMENT_DIR, ROBOT_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from line_planner import is_obstacle
from measurement_config import read_measurement_config
from robot_connection import assert_remote_control, get_rtde_receive
from run_measurements import translate_along_line


ROBOT_IP = "192.168.3.10"
MEASUREMENT_CONFIG_FILE = PROJECT_ROOT / "Configuration" / "measurement_config.json"

# Assumption: the robot starts at p_start_h, i.e. line position 0 in high mode.
TARGET_LINE_POSITION = 0.8


if __name__ == "__main__":
    config = read_measurement_config(MEASUREMENT_CONFIG_FILE, verbose=True)

    if TARGET_LINE_POSITION < 0 or TARGET_LINE_POSITION > config["line"]["length"]:
        raise ValueError("TARGET_LINE_POSITION must be inside the configured line length.")

    if is_obstacle(TARGET_LINE_POSITION, config):
        raise ValueError(f"TARGET_LINE_POSITION {TARGET_LINE_POSITION} m is inside the obstacle.")

    input(
        f"Press Enter to move high-mode line position {TARGET_LINE_POSITION:.3f} m "
        "from p_start_h, or Ctrl+C to cancel."
    )
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    try:
        translate_along_line(ROBOT_IP, rtde_receive, config, TARGET_LINE_POSITION)
        print(f"Reached high-mode line position {TARGET_LINE_POSITION:.3f} m")
    finally:
        rtde_receive.disconnect()
