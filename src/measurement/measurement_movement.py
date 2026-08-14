"""Robot movements used while traversing the measurement line."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import high_low_movement, normalize, scale
from robot_move import translate_tool


def motion_parameters(config: dict) -> tuple[float, float]:
    """Return the general linear motion acceleration and speed."""

    motion = config["motion"]
    if motion["type"].lower() != "l":
        raise ValueError("Measurement motion type must be 'l'.")
    if motion["acceleration"] <= 0 or motion["speed"] <= 0:
        raise ValueError("Measurement acceleration and speed must be positive.")
    return motion["acceleration"], motion["speed"]


def high_to_low(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the safe high plane to the low measurement plane."""

    movement = high_low_movement(config)
    if movement is None:
        return
    acceleration, speed = motion_parameters(config)
    direction, distance = movement
    offset = scale(normalize(direction), distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def low_to_high(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the low measurement plane back to the safe high plane."""

    movement = high_low_movement(config)
    if movement is None:
        return
    acceleration, speed = motion_parameters(config)
    direction, distance = movement
    offset = scale(normalize(direction), -distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def translate_along_line(robot_ip: str, rtde_receive, config: dict, distance: float) -> None:
    """Move the requested distance along the configured measurement line."""

    line = config["line"]
    acceleration, speed = motion_parameters(config)
    direction = normalize(line["direction_start_end"])
    offset = scale(direction, distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)
