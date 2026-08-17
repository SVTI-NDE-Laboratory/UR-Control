"""Robot movements used while traversing the measurement line."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import (
    POINT_TO_POINT,
    high_low_movement,
    line_geometry,
    line_parameters,
    normalize,
    point_pose,
    scale,
)
from robot_move import movel_pose, translate_tool


def motion_parameters(config: dict) -> tuple[float, float]:
    """Return the general linear motion acceleration and speed."""

    motion = config["motion"]
    if motion["type"].lower() != "l":
        raise ValueError("Measurement motion type must be 'l'.")
    if motion["acceleration"] <= 0 or motion["speed"] <= 0:
        raise ValueError("Measurement acceleration and speed must be positive.")
    return motion["acceleration"], motion["speed"]


def high_to_low(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
) -> None:
    """Move from the safe high plane to the low measurement plane."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        acceleration, speed = motion_parameters(config)
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(geometry, line_position, "low"),
            acceleration,
            speed,
            30.0,
        )
        return

    movement = high_low_movement(config, routines_data)
    if movement is None:
        return
    acceleration, speed = motion_parameters(config)
    direction, distance = movement
    offset = scale(normalize(direction), distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def low_to_high(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
) -> None:
    """Move from the low measurement plane back to the safe high plane."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        acceleration, speed = motion_parameters(config)
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(geometry, line_position, "high"),
            acceleration,
            speed,
            30.0,
        )
        return

    movement = high_low_movement(config, routines_data)
    if movement is None:
        return
    acceleration, speed = motion_parameters(config)
    direction, distance = movement
    offset = scale(normalize(direction), -distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def translate_along_line(
    robot_ip: str,
    rtde_receive,
    config: dict,
    distance: float,
    routines_data: dict | None = None,
    target_position: float | None = None,
    height_mode: str = "low",
) -> None:
    """Move along the configured line, relatively or to an absolute taught line pose."""

    geometry = line_geometry(config, routines_data)
    acceleration, speed = motion_parameters(config)
    if geometry["method"] == POINT_TO_POINT:
        if target_position is None:
            raise ValueError("Point-to-point movement requires target_position.")
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(geometry, target_position, height_mode),
            acceleration,
            speed,
            30.0,
        )
        return

    direction = normalize(line_parameters(config)["direction_start_end"])
    offset = scale(direction, distance)
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def return_to_start_high(
    robot_ip: str, rtde_receive, config: dict, routines_data: dict | None = None
) -> None:
    """Return to the exact safe start pose after a failed measurement."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != POINT_TO_POINT:
        raise ValueError("Exact safe-start return is only used by point-to-point mode.")
    acceleration, speed = motion_parameters(config)
    movel_pose(
        robot_ip,
        rtde_receive,
        geometry["safe_pose"],
        acceleration,
        speed,
        30.0,
    )
