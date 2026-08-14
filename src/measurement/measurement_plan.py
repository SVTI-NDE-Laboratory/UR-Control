"""Create an extensible JSON plan of all scheduled measurement positions."""

import json
from datetime import datetime
from pathlib import Path

from line_planner import is_obstacle, line_positions


def create_measurement_plan(config: dict) -> dict:
    """Return a plan containing only positions where measurements will occur."""

    points = []
    for line_index, line_position in line_positions(config):
        if is_obstacle(line_position, config):
            continue
        points.append(
            {
                "line_index": line_index,
                "line_position": round(line_position, 12),
                "data": {},
            }
        )

    return {
        "schema_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "units": {"line_position": "m"},
        "points": points,
    }


def write_measurement_plan(path: str | Path, config: dict) -> dict:
    """Atomically write and return the measurement plan."""

    plan = create_measurement_plan(config)
    plan_path = Path(path)
    temporary_path = plan_path.with_suffix(plan_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(plan_path)
    return plan
