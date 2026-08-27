"""Create an extensible JSON plan of all scheduled measurement positions."""

import json
from datetime import datetime
from pathlib import Path

from line_planner import POINT_TO_POINT, is_obstacle, line_geometry, line_positions, point_pose


def display_tcp_pose(pose: list[float]) -> list[float]:
    """Return a TCP pose with XYZ in millimetres and rotation unchanged."""

    return [pose[index] * 1000.0 for index in range(3)] + list(pose[3:6])


def create_measurement_plan(config: dict, routines_data: dict | None = None) -> dict:
    """Return a plan containing only positions where measurements will occur."""

    points = []
    geometry = line_geometry(config, routines_data)
    for _, line_position in line_positions(config, routines_data):
        if is_obstacle(line_position, config):
            continue
        point = {
            "measurement_index": len(points) + 1,
            "line_position": round(line_position, 12),
            "data": {
                "timestamp": None,
                "force_reached": None,
            },
        }
        if geometry["method"] == POINT_TO_POINT:
            point["tcp_pose"] = [
                round(value, 12)
                for value in display_tcp_pose(point_pose(geometry, line_position))
            ]
        points.append(point)

    units = {"line_position": "mm"}
    if geometry["method"] == POINT_TO_POINT:
        units["tcp_pose"] = ["mm", "mm", "mm", "rad", "rad", "rad"]

    return {
        "schema_version": 3,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "line_method": geometry["method"],
        "units": units,
        "points": points,
    }


def write_measurement_plan(
    path: str | Path, config: dict, routines_data: dict | None = None
) -> dict:
    """Atomically write and return the measurement plan."""

    plan = create_measurement_plan(config, routines_data)
    plan_path = Path(path)
    temporary_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(plan_path)
    return plan


def record_measurement_result(
    path: str | Path,
    measurement_index: int,
    force_reached: bool,
    timestamp: str | None = None,
) -> dict:
    """Atomically record one completed force attempt in an existing plan."""

    plan_path = Path(path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    try:
        point = next(
            point
            for point in plan["points"]
            if point["measurement_index"] == measurement_index
        )
    except (KeyError, StopIteration) as error:
        raise ValueError(
            f"Measurement index {measurement_index} is not present in the plan."
        ) from error

    point.setdefault("data", {}).update(
        {
            "timestamp": timestamp
            or datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "force_reached": bool(force_reached),
        }
    )
    temporary_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(plan_path)
    return point
