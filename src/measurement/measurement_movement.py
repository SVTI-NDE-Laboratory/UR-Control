"""Robot movements used while traversing the measurement line."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import normalize, scale
from robot_move import translate_tool


def high_to_low(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the safe high plane to the low measurement plane."""

    obstacle = config["obstacle"]
    measurement = config["measurement"]
    direction = normalize(obstacle["direction_high_low"])
    offset = scale(direction, obstacle["high_low_distance"])
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)


def low_to_high(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the low measurement plane back to the safe high plane."""

    obstacle = config["obstacle"]
    measurement = config["measurement"]
    direction = normalize(obstacle["direction_high_low"])
    offset = scale(direction, -obstacle["high_low_distance"])
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)


def translate_along_line(robot_ip: str, rtde_receive, config: dict, distance: float) -> None:
    """Move the requested distance along the configured measurement line."""

    line = config["line"]
    measurement = config["measurement"]
    direction = normalize(line["direction_start_end"])
    offset = scale(direction, distance)
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)
