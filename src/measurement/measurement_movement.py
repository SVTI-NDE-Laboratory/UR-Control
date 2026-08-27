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
    millimetres_to_metres,
    normalize,
    point_pose,
    scale,
)
from robot_move import movel_pose, translate_tool


def motion_parameters(config: dict) -> tuple[float, float]:
    """Return linear motion acceleration/speed converted from mm units to metres."""

    motion = config["motion"]
    if motion["type"].lower() != "l":
        raise ValueError("Measurement motion type must be 'l'.")
    if motion["acceleration"] <= 0 or motion["speed"] <= 0:
        raise ValueError("Measurement acceleration and speed must be positive.")
    return (
        millimetres_to_metres(motion["acceleration"]),
        millimetres_to_metres(motion["speed"]),
    )


def high_to_low(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
    lateral_offset: bool = True,
) -> None:
    """Move from the safe high plane to the low measurement plane."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        acceleration, speed = motion_parameters(config)
        if lateral_offset and abs(geometry["offset_y"]) > 1e-12:
            movel_pose(
                robot_ip,
                rtde_receive,
                point_pose(geometry, line_position, "low", lateral_offset=False),
                acceleration,
                speed,
                30.0,
            )
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(
                geometry,
                line_position,
                "low",
                lateral_offset=lateral_offset,
            ),
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
    offset = scale(normalize(direction), millimetres_to_metres(distance))
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def low_to_high(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
    lateral_offset: bool = True,
) -> None:
    """Move from the low measurement plane back to the safe high plane."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        acceleration, speed = motion_parameters(config)
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(
                geometry,
                line_position,
                "high",
                lateral_offset=lateral_offset,
            ),
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
    offset = scale(normalize(direction), -millimetres_to_metres(distance))
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def translate_along_line(
    robot_ip: str,
    rtde_receive,
    config: dict,
    distance: float,
    routines_data: dict | None = None,
    target_position: float | None = None,
    height_mode: str = "low",
    lateral_offset: bool = True,
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
            point_pose(
                geometry,
                target_position,
                height_mode,
                lateral_offset=lateral_offset,
            ),
            acceleration,
            speed,
            30.0,
        )
        return

    direction = normalize(line_parameters(config)["direction_start_end"])
    offset = scale(direction, millimetres_to_metres(distance))
    translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 30.0)


def move_to_start_high(
    robot_ip: str, rtde_receive, config: dict, routines_data: dict | None = None
) -> None:
    """Move to the effective safe start pose without applying any Y offset."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != POINT_TO_POINT:
        return
    if max(abs(value) for value in geometry["start_x_vector"]) <= 1e-12:
        return
    acceleration, speed = motion_parameters(config)
    movel_pose(
        robot_ip,
        rtde_receive,
        geometry["zero_y_safe_pose"],
        acceleration,
        speed,
        30.0,
    )


def move_to_zero_y_low(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
) -> None:
    """Move from a Y-offset low point back to the taught X/Z line."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != POINT_TO_POINT:
        return
    if abs(geometry["offset_y"]) <= 1e-12:
        return
    acceleration, speed = motion_parameters(config)
    movel_pose(
        robot_ip,
        rtde_receive,
        point_pose(geometry, line_position, "low", lateral_offset=False),
        acceleration,
        speed,
        30.0,
    )


def move_to_zero_y_high(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None = None,
    line_position: float = 0.0,
) -> None:
    """Move from a Y-offset high point back to the taught X/Z line."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != POINT_TO_POINT:
        return
    if abs(geometry["offset_y"]) <= 1e-12:
        return
    acceleration, speed = motion_parameters(config)
    movel_pose(
        robot_ip,
        rtde_receive,
        point_pose(geometry, line_position, "high", lateral_offset=False),
        acceleration,
        speed,
        30.0,
    )


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
