"""Create an extensible JSON plan of all scheduled measurement positions."""

import json
from datetime import datetime
from pathlib import Path

from wall_coordinates import local_to_wall, wall_reference
from atomic_json import write_json_atomic
from line_planner import POINT_TO_POINT, is_obstacle, line_geometry, line_positions, point_pose, point_is_selected, selected_line_positions


RESULT_STATUSES = {"measured", "simulation", "approach_limit", "timeout", "stopped", "error"}


def display_tcp_pose(pose: list[float]) -> list[float]:
    """Return a TCP pose with XYZ in millimetres and rotation unchanged."""

    return [pose[index] * 1000.0 for index in range(3)] + list(pose[3:6])


def create_measurement_plan(config: dict, routines_data: dict | None = None) -> dict:
    """Return a plan for every sampled line point.

    ``point_number`` is the original one-based sample number. Obstructed
    and unselected points remain with ``scheduled=false`` and a skip reason.
    Plane X/Y use the installation wall reference when configured, matching
    flexible measurement. Positive wall Y points upward; TCP poses stay in base coordinates.
    """

    points = []
    geometry = line_geometry(config, routines_data)
    for sample_index, line_position in line_positions(config, routines_data):
        blocked = is_obstacle(line_position, config)
        selected = point_is_selected(sample_index + 1, config)
        point = {
            "point_number": sample_index + 1,
            "plane_position_x": round(local_to_wall(geometry.get("x_start", 0.0) + line_position, geometry.get("offset_y", 0.0))[0], 12),
            "plane_position_y": local_to_wall(0.0, geometry.get("offset_y", 0.0))[1],
            "scheduled": selected and not blocked,
            "data": {
                "timestamp": None,
                "status": None,
            },
        }
        if blocked:
            point["skip_reason"] = "obstacle"
        elif not selected:
            point["skip_reason"] = "not_selected"
        if geometry["method"] == POINT_TO_POINT:
            point["tcp_pose"] = [
                round(value, 12)
                for value in display_tcp_pose(point_pose(geometry, line_position))
            ]
        points.append(point)

    units = {"plane_position_x": "mm", "plane_position_y": "mm"}
    if geometry["method"] == POINT_TO_POINT:
        units["tcp_pose"] = ["mm", "mm", "mm", "rad", "rad", "rad"]

    return {
        "schema_version": 7,
        "coordinate_system": "wall" if wall_reference() else "local",
        "wall_coordinates": wall_reference(),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "line_method": geometry["method"],
        "units": units,
        "points": points,
    }


def first_measurable_index(config: dict, routines_data: dict | None = None) -> int | None:
    """Return the first selected, unobstructed one-based point ID."""

    for sample_index, line_position in selected_line_positions(config, routines_data):
        return sample_index + 1
    return None


def write_measurement_plan(
    path: str | Path, config: dict, routines_data: dict | None = None
) -> dict:
    """Atomically write and return the measurement plan."""

    plan = create_measurement_plan(config, routines_data)
    write_json_atomic(path, plan)
    return plan


def record_measurement_result(
    path: str | Path,
    measurement_index: int,
    status: str,
    timestamp: str | None = None,
    message: str | None = None,
) -> dict:
    """Record an attempt outcome; null status is reserved for unattempted points.

    approach_limit covers controller status 2, which combines travel limit and
    approach timeout. timeout covers explicit Python/controller timeouts.
    """

    if status not in RESULT_STATUSES:
        raise ValueError(f"Unknown measurement result status: {status!r}")
    plan_path = Path(path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    try:
        point = next(
            point
            for point in plan["points"]
            if point.get("point_number", point.get("measurement_index")) == measurement_index
        )
    except (KeyError, StopIteration) as error:
        raise ValueError(
            f"Point number {measurement_index} is not present in the measurement results."
        ) from error

    data = point.setdefault("data", {})
    data.pop("force_reached", None)
    data.pop("message", None)
    data.update(
        {
            "timestamp": timestamp
            or datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "status": status,
        }
    )
    if message is not None:
        data["message"] = message
    write_json_atomic(plan_path, plan)
    return point
