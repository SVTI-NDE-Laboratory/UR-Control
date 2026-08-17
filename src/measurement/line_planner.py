"""Pure measurement-line and obstacle geometry."""

import math


TRANSLATION = "translation"
POINT_TO_POINT = "point_to_point"


def line_method(config: dict) -> str:
    """Return and validate the configured line-planning method."""

    method = config["line"].get("method", TRANSLATION)
    if method not in {TRANSLATION, POINT_TO_POINT}:
        raise ValueError(
            "Line method must be 'translation' or 'point_to_point'."
        )
    return method


def line_parameters(config: dict) -> dict:
    """Return method parameters, accepting the old flat translation schema."""

    line = config["line"]
    if "parameters" in line:
        return line["parameters"]

    # Compatibility for saved configurations created before high/low geometry
    # moved from the obstacle section into the line section.
    parameters = dict(line)
    obstacle = config.get("obstacle") or {}
    for key in ("high_low_distance", "direction_high_low"):
        if key not in parameters and key in obstacle:
            parameters[key] = obstacle[key]
    return parameters


def obstacle_interval(config: dict) -> tuple[float, float] | None:
    """Return the configured obstacle interval, or ``None`` when omitted."""

    obstacle = config.get("obstacle") or {}
    has_start = "start" in obstacle
    has_end = "end" in obstacle
    if has_start != has_end:
        raise ValueError("Obstacle start and end must either both be set or both be omitted.")
    if not has_start:
        return None

    start = obstacle["start"]
    end = obstacle["end"]
    if start < 0:
        raise ValueError("Obstacle start must not be negative.")
    if start > end:
        raise ValueError("Obstacle start must not be greater than obstacle end.")
    return start, end


def normalize(vector: list[float]) -> list[float]:
    """Return a unit vector in the same direction."""

    if len(vector) != 3:
        raise ValueError("Direction vectors must contain exactly three values.")
    length = math.sqrt(sum(value * value for value in vector))
    if length <= 1e-12:
        raise ValueError("Direction vectors cannot be zero.")
    return [value / length for value in vector]


def scale(vector: list[float], distance: float) -> list[float]:
    """Scale a vector by a distance."""

    return [value * distance for value in vector]


def _waypoint_pose(routines_data: dict | None, name: str) -> list[float]:
    """Return a validated Cartesian waypoint pose."""

    if routines_data is None:
        raise ValueError(
            f"Routine data is required to resolve point-to-point waypoint '{name}'."
        )
    try:
        waypoint = routines_data["waypoints"][name]
    except KeyError as error:
        raise ValueError(f"Waypoint '{name}' is not defined.") from error
    pose = waypoint.get("p")
    if not isinstance(pose, list) or len(pose) != 6:
        raise ValueError(f"Waypoint '{name}' must contain a six-value Cartesian pose 'p'.")
    return pose


def line_geometry(config: dict, routines_data: dict | None = None) -> dict:
    """Resolve line length, sampling, and waypoint geometry."""

    method = line_method(config)
    parameters = line_parameters(config)

    if method == TRANSLATION:
        length = parameters.get("line_length", parameters.get("length"))
        increment = parameters.get("increment")
        if length is None or increment is None:
            raise ValueError("Translation requires line_length and increment.")
        if length <= 0 or increment <= 0:
            raise ValueError("Line length and increment must be positive.")
        direction = parameters.get("direction_start_end")
        if direction is None:
            raise ValueError("Translation requires direction_start_end.")
        normalize(direction)
        return {
            "method": method,
            "length": float(length),
            "increment": float(increment),
            "direction_start_end": direction,
        }

    start_name = parameters.get("start_point")
    end_name = parameters.get("end_point")
    count = parameters.get("number_of_measurements")
    requested_increment = parameters.get("increment")
    spacing_source = parameters.get("spacing_source", "increment")
    if not start_name or not end_name:
        raise ValueError("Point-to-point requires start_point and end_point names.")

    start_pose = _waypoint_pose(routines_data, start_name)
    end_pose = _waypoint_pose(routines_data, end_name)
    displacement = [end_pose[index] - start_pose[index] for index in range(3)]
    length = math.sqrt(sum(value * value for value in displacement))
    if length <= 1e-12:
        raise ValueError("Point-to-point start and end positions must be different.")

    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count < 2
    ):
        raise ValueError("number_of_measurements must be an integer of at least 2.")
    if requested_increment is not None and requested_increment <= 0:
        raise ValueError("Point-to-point increment must be positive.")
    if spacing_source not in {"increment", "count"}:
        raise ValueError("Point-to-point spacing_source must be 'increment' or 'count'.")
    if spacing_source == "count":
        if count is None:
            raise ValueError("Point-to-point count spacing requires number_of_measurements.")
        increment = length / (count - 1)
    elif requested_increment is not None:
        interval_ratio = length / requested_increment
        nearest_integer = round(interval_ratio)
        interval_count = (
            nearest_integer
            if math.isclose(interval_ratio, nearest_integer, rel_tol=1e-9, abs_tol=1e-12)
            else math.floor(interval_ratio)
        )
        if interval_count < 1:
            raise ValueError(
                "Point-to-point increment must not exceed the line length."
            )
        count = interval_count + 1
        increment = float(requested_increment)
    else:
        raise ValueError(
            "Point-to-point requires a positive increment or number_of_measurements."
        )

    safe_name = parameters.get("safe_start_point", "p_start_h")
    safe_pose = _waypoint_pose(routines_data, safe_name)
    clearance_offset = [safe_pose[index] - start_pose[index] for index in range(3)]
    clearance_distance = math.sqrt(sum(value * value for value in clearance_offset))
    if clearance_distance <= 1e-12:
        raise ValueError(
            f"Safe waypoint '{safe_name}' and low waypoint '{start_name}' "
            "must have different Cartesian positions."
        )

    return {
        "method": method,
        "length": length,
        "increment": increment,
        "number_of_measurements": count,
        "spacing_source": spacing_source,
        "start_name": start_name,
        "end_name": end_name,
        "safe_name": safe_name,
        "start_pose": list(start_pose),
        "end_pose": list(end_pose),
        "safe_pose": list(safe_pose),
        "clearance_offset": clearance_offset,
        "clearance_distance": clearance_distance,
    }


def high_low_movement(
    config: dict, routines_data: dict | None = None
) -> tuple[list[float], float] | None:
    """Return high-to-low direction and distance for the selected method."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        # Direction is from the taught safe pose to the low measurement pose.
        direction = normalize([-value for value in geometry["clearance_offset"]])
        return direction, geometry["clearance_distance"]

    parameters = line_parameters(config)
    has_direction = "direction_high_low" in parameters
    has_distance = "high_low_distance" in parameters
    if has_direction != has_distance:
        raise ValueError(
            "High-to-low direction and distance must either both be set or both be omitted."
        )
    if not has_direction:
        raise ValueError(
            "Translation requires high_low_distance and direction_high_low."
        )
    if parameters["high_low_distance"] <= 0:
        raise ValueError("High-to-low distance must be positive.")
    normalize(parameters["direction_high_low"])
    return parameters["direction_high_low"], parameters["high_low_distance"]


def point_pose(geometry: dict, position: float, height_mode: str = "low") -> list[float]:
    """Return the absolute point-to-point pose at a distance along the line."""

    fraction = position / geometry["length"]
    start_pose = geometry["start_pose"]
    end_pose = geometry["end_pose"]
    pose = [
        start_pose[index] + fraction * (end_pose[index] - start_pose[index])
        for index in range(3)
    ] + list(start_pose[3:6])
    if height_mode == "high":
        for index in range(3):
            pose[index] += geometry["clearance_offset"][index]
    elif height_mode != "low":
        raise ValueError("height_mode must be 'low' or 'high'.")
    return pose


def is_obstacle(position: float, config: dict) -> bool:
    """Return whether a scalar line position is inside the obstacle interval."""

    interval = obstacle_interval(config)
    if interval is None:
        return False
    start, end = interval
    return start - 1e-9 <= position <= end + 1e-9


def crosses_obstacle(start_position: float, end_position: float, config: dict) -> bool:
    """Return whether a translation segment touches the obstacle interval."""

    interval = obstacle_interval(config)
    if interval is None:
        return False
    obstacle_start, obstacle_end = interval
    segment_start = min(start_position, end_position)
    segment_end = max(start_position, end_position)
    return segment_start <= obstacle_end + 1e-9 and segment_end >= obstacle_start - 1e-9


def line_positions(
    config: dict, routines_data: dict | None = None
) -> list[tuple[int, float]]:
    """Return all measurement positions as index/distance pairs."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] == POINT_TO_POINT:
        return [
            (index, index * geometry["increment"])
            for index in range(geometry["number_of_measurements"])
        ]

    positions = []
    index = 0
    position = 0.0
    while position <= geometry["length"] + 1e-9:
        positions.append((index, position))
        index += 1
        position = index * geometry["increment"]
    return positions


def next_measurement_step(
    positions: list[tuple[int, float]], start_step: int, config: dict
) -> int | None:
    """Return the next step that is not inside the obstacle."""

    for step in range(start_step, len(positions)):
        if not is_obstacle(positions[step][1], config):
            return step
    return None
