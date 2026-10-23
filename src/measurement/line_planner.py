"""Pure measurement-line and obstacle geometry."""

import math


TRANSLATION = "translation"
POINT_TO_POINT = "point_to_point"
MM_PER_METRE = 1000.0
X_SCOPE_ALLOWANCE_MM = 100.0


def as_millimetres(value: float) -> float:
    """Return ``value`` as a float in millimetres.

    Measurement configuration values are stored in millimetres. Robot poses from
    RTDE/routine files remain in metres because that is the UR native format.
    """

    return float(value)


def millimetres_to_metres(value: float) -> float:
    """Convert a distance from millimetres to metres for robot API calls."""

    return float(value) / MM_PER_METRE


def line_method(config: dict) -> str:
    """Return and validate the configured line-planning method."""

    method = config["line"].get("method", POINT_TO_POINT)
    if method not in {TRANSLATION, POINT_TO_POINT}:
        raise ValueError(
            "Line method must be 'translation' or 'point_to_point'."
        )
    return method


def line_parameters(config: dict) -> dict:
    """Return flat line settings, accepting archived nested configurations."""

    line = config["line"]
    if "parameters" in line:
        line = line["parameters"]

    # Compatibility for saved configurations created before high/low geometry
    # moved from the obstacle section into the line section.
    parameters = dict(line)
    for stored, internal in (("steps", "increment"), ("nb_points", "number_of_measurements")):
        if stored in parameters:
            parameters[internal] = parameters.pop(stored)
    if "spacing_source" in parameters:
        parameters["spacing_source"] = {"steps": "increment", "nb_points": "count"}.get(parameters["spacing_source"], parameters["spacing_source"])
    obstacle = config.get("obstacle") or {}
    for key in ("high_low_distance", "direction_high_low"):
        if key not in parameters and key in obstacle:
            parameters[key] = obstacle[key]
    return parameters


def obstacle_interval(config: dict) -> tuple[float, float] | None:
    """Return obstacle bounds relative to the selected segment's start.

    Point-to-point obstacle entries use the taught X origin, like X Start/End.
    Motion planning uses distance from X Start, so convert at this boundary.
    """

    obstacle = config.get("obstacle") or {}
    if "present" in obstacle and not isinstance(obstacle["present"], bool):
        raise ValueError("Obstacle present must be true or false.")
    if obstacle.get("present") is False:
        return None
    if "position" in obstacle:
        width = obstacle.get("width", config.get("obstacle_width", 200.0))
        if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
            raise ValueError("Obstacle width must be positive and finite (mm).")
        center = obstacle["position"]
        if isinstance(center, bool) or not isinstance(center, (int, float)) or not math.isfinite(center):
            raise ValueError("Obstacle position must be a finite number (mm).")
        half_width = width / 2.0
        start = obstacle["position"] - half_width
        end = obstacle["position"] + half_width
    else:
        has_start = "start" in obstacle
        has_end = "end" in obstacle
        if has_start != has_end:
            raise ValueError("Obstacle start and end must either both be set or both be omitted.")
        if not has_start:
            return None
        start = obstacle["start"]
        end = obstacle["end"]
    if not all(math.isfinite(value) for value in (start, end)):
        raise ValueError("Obstacle positions must be finite numbers.")
    if start < 0:
        raise ValueError("Obstacle start must not be negative.")
    if start > end:
        raise ValueError("Obstacle start must not be greater than obstacle end.")
    origin = 0.0
    if "line" in config and line_method(config) == POINT_TO_POINT:
        parameters = line_parameters(config)
        origin = float(parameters.get("x_start", parameters.get("offset_x", 0.0)))
    return start - origin, end - origin


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


def add_vectors(*vectors: list[float]) -> list[float]:
    """Return the component-wise sum of three-dimensional vectors."""

    return [sum(vector[index] for vector in vectors) for index in range(3)]


def cross(left: list[float], right: list[float]) -> list[float]:
    """Return the three-dimensional cross product ``left x right``."""

    return [
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    ]


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


def point_to_point_offsets(parameters: dict, line_length: float) -> tuple[float, float, float]:
    """Return configured point-to-point X start/end and Y offset in millimetres."""

    x_start = float(parameters.get("x_start", parameters.get("offset_x", 0.0)))
    x_end = float(parameters.get("x_end", line_length))
    if x_end == 0 and parameters.get("auto_fit", True):
        x_end = line_length
    return x_start, x_end, float(parameters.get("offset_y", 0.0))


def point_to_point_offset_geometry(
    parameters: dict,
    safe_pose: list[float],
    start_pose: list[float],
    end_pose: list[float],
    line_length: float,
) -> dict:
    """Resolve the selected point-to-point segment and lateral offset.

    X follows ``p_start_l -> p_end_l``, allowing up to 100 mm beyond the taught
    endpoints. Z is used only to derive the local point-to-point frame from
    ``p_start_h -> p_start_l``. Y is perpendicular to the X/Z plane using the
    right-hand convention
    ``y = z cross x``.
    """

    x_start, x_end, offset_y = point_to_point_offsets(parameters, line_length)
    if not all(math.isfinite(value) for value in (x_start, x_end, offset_y)):
        raise ValueError("X Start, X End and Y Offset must be finite numbers.")
    if any(value < -X_SCOPE_ALLOWANCE_MM - 1e-9 or
           value > line_length + X_SCOPE_ALLOWANCE_MM + 1e-9
           for value in (x_start, x_end)):
        raise ValueError(
            f"X Start and X End must be between {-X_SCOPE_ALLOWANCE_MM:g} and "
            f"{line_length + X_SCOPE_ALLOWANCE_MM:g} mm "
            f"(at most {X_SCOPE_ALLOWANCE_MM:g} mm beyond the taught line)."
        )
    single_point = parameters.get("auto_fit", True) is False and parameters.get("number_of_measurements") == 1
    if x_start > x_end or (x_start == x_end and not single_point):
        raise ValueError("X Start must be smaller than X End.")

    z_axis = normalize([start_pose[index] - safe_pose[index] for index in range(3)])
    x_axis = normalize([end_pose[index] - start_pose[index] for index in range(3)])
    y_axis = None

    if abs(offset_y) > 1e-12:
        try:
            y_axis = normalize(cross(z_axis, x_axis))
        except ValueError as error:
            raise ValueError(
                "Offset Y cannot be resolved because p_start_l -> p_end_l "
                "and p_start_h -> p_start_l are parallel."
            ) from error
    else:
        y_axis = [0.0, 0.0, 0.0]

    start_x_vector = scale(x_axis, millimetres_to_metres(x_start))
    end_x_vector = scale(x_axis, millimetres_to_metres(x_end))
    y_offset_vector = scale(y_axis, millimetres_to_metres(offset_y))

    return {
        "x_start": x_start,
        "x_end": x_end,
        "offset_y": offset_y,
        "offset_vector": add_vectors(start_x_vector, y_offset_vector),
        "start_x_vector": start_x_vector,
        "end_x_vector": end_x_vector,
        "y_offset_vector": y_offset_vector,
        "x_axis": x_axis,
        "y_axis": y_axis,
        "z_axis": z_axis,
    }


def line_scope_warning(geometry: dict) -> str | None:
    """Describe a selected segment outside the taught line for start approval."""

    if geometry["method"] != POINT_TO_POINT:
        return None
    start, end, taught = (geometry[key] for key in ("x_start", "x_end", "taught_length"))
    if start >= -1e-9 and end <= taught + 1e-9:
        return None
    def shown(value):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return "0" if text == "-0" else text

    return (
        f"The measurement line goes slightly outside the taught range "
        f"(0 to {shown(taught)} mm). X Start is {shown(start)} mm and X End is {shown(end)} mm. "
        "Moving beyond the taught endpoints could reach a singularity or cause "
        "unexpected movements. Do you want to start this automatic program?"
    )


def shifted_pose(pose: list[float], offset_vector: list[float]) -> list[float]:
    """Return a pose translated by a base-frame offset while keeping orientation."""

    return add_vectors(pose[:3], offset_vector) + list(pose[3:6])


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
            "length": as_millimetres(length),
            "increment": as_millimetres(increment),
            "direction_start_end": direction,
        }

    start_name = parameters.get("start_point")
    end_name = parameters.get("end_point")
    count = parameters.get("number_of_measurements")
    requested_increment = parameters.get("increment")
    spacing_source = parameters.get("spacing_source", "increment")
    if not start_name or not end_name:
        raise ValueError("Point-to-point requires start_point and end_point names.")

    taught_start_pose = _waypoint_pose(routines_data, start_name)
    taught_end_pose = _waypoint_pose(routines_data, end_name)
    displacement = [taught_end_pose[index] - taught_start_pose[index] for index in range(3)]
    taught_length = math.sqrt(sum(value * value for value in displacement)) * MM_PER_METRE
    if taught_length <= 1e-12:
        raise ValueError("Point-to-point start and end positions must be different.")

    safe_name = parameters.get("safe_start_point", "p_start_h")
    taught_safe_pose = _waypoint_pose(routines_data, safe_name)
    auto_fit = parameters.get("auto_fit", True)
    if not isinstance(auto_fit, bool):
        raise ValueError("auto_fit must be true or false.")
    if not auto_fit:
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("number_of_measurements must be a positive integer.")
        if requested_increment is None or not math.isfinite(requested_increment) or requested_increment <= 0:
            raise ValueError("Point-to-point increment must be positive and finite.")
        parameters = dict(parameters)
        parameters["x_end"] = float(parameters.get("x_start", parameters.get("offset_x", 0.0))) + (count - 1) * requested_increment
    offset_geometry = point_to_point_offset_geometry(
        parameters,
        taught_safe_pose,
        taught_start_pose,
        taught_end_pose,
        taught_length,
    )
    length = offset_geometry["x_end"] - offset_geometry["x_start"]

    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count < 1
    ):
        raise ValueError("number_of_measurements must be a positive integer.")
    if requested_increment is not None and (not math.isfinite(requested_increment) or requested_increment <= 0):
        raise ValueError("Point-to-point increment must be positive and finite.")
    if spacing_source not in {"increment", "count"}:
        raise ValueError("Point-to-point spacing_source must be 'increment' or 'count'.")
    if not auto_fit:
        increment = float(requested_increment)
    elif spacing_source == "count":
        if count is None or count < 2:
            raise ValueError("Automatic Fit by count requires at least 2 measurements.")
        increment = length / (count - 1)
    elif requested_increment is not None:
        interval_ratio = length / requested_increment
        nearest_integer = round(interval_ratio)
        interval_count = (
            nearest_integer
            if abs(nearest_integer * requested_increment - length) <= 1e-9
            else math.floor(interval_ratio)
        )
        count = interval_count + 1
        increment = float(requested_increment)
    else:
        raise ValueError(
            "Point-to-point requires a positive increment or number_of_measurements."
        )

    start_pose = shifted_pose(
        taught_start_pose,
        add_vectors(offset_geometry["start_x_vector"], offset_geometry["y_offset_vector"]),
    )
    end_pose = shifted_pose(
        taught_start_pose,
        add_vectors(offset_geometry["end_x_vector"], offset_geometry["y_offset_vector"]),
    )
    safe_pose = shifted_pose(
        taught_safe_pose,
        add_vectors(offset_geometry["start_x_vector"], offset_geometry["y_offset_vector"]),
    )
    zero_y_start_pose = shifted_pose(taught_start_pose, offset_geometry["start_x_vector"])
    zero_y_end_pose = shifted_pose(taught_start_pose, offset_geometry["end_x_vector"])
    zero_y_safe_pose = shifted_pose(taught_safe_pose, offset_geometry["start_x_vector"])
    clearance_offset = [safe_pose[index] - start_pose[index] for index in range(3)]
    clearance_distance = (
        math.sqrt(sum(value * value for value in clearance_offset)) * MM_PER_METRE
    )
    if clearance_distance <= 1e-12:
        raise ValueError(
            f"Safe waypoint '{safe_name}' and low waypoint '{start_name}' "
            "must have different Cartesian positions."
        )

    return {
        "method": method,
        "length": length,
        "taught_length": taught_length,
        "increment": increment,
        "number_of_measurements": count,
        "spacing_source": spacing_source,
        "start_name": start_name,
        "end_name": end_name,
        "safe_name": safe_name,
        "start_pose": list(start_pose),
        "end_pose": list(end_pose),
        "safe_pose": list(safe_pose),
        "zero_y_start_pose": list(zero_y_start_pose),
        "zero_y_end_pose": list(zero_y_end_pose),
        "zero_y_safe_pose": list(zero_y_safe_pose),
        "clearance_offset": clearance_offset,
        "clearance_distance": clearance_distance,
        **offset_geometry,
    }


def high_low_movement(
    config: dict, routines_data: dict | None = None
) -> tuple[list[float], float] | None:
    """Return high-to-low direction and distance in millimetres."""

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


def point_pose(
    geometry: dict,
    position: float,
    height_mode: str = "low",
    lateral_offset: bool = True,
) -> list[float]:
    """Return the absolute point-to-point pose at a millimetre line position."""

    if lateral_offset:
        start_pose = geometry["start_pose"]
    else:
        start_pose = geometry["zero_y_start_pose"]
    pose = [
        start_pose[index] + geometry["x_axis"][index] * millimetres_to_metres(position)
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


def start_entry_crosses_obstacle(config: dict, geometry: dict, first_position: float = 0.0) -> bool:
    """Check the approach from the taught start to the first selected point."""
    return crosses_obstacle(-geometry.get("x_start", 0.0), first_position, config)


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
    """Return the next selected step outside the obstacle."""

    for step in range(start_step, len(positions)):
        if point_is_selected(positions[step][0] + 1, config) and not is_obstacle(positions[step][1], config):
            return step
    return None


def point_is_selected(point_id: int, config: dict) -> bool:
    """Apply selection to original one-based point IDs, independently of obstacles."""
    selection = config.get("points_selection", {})
    mode = selection.get("mode", "all")
    if mode == "from_point":
        return point_id >= selection.get("from_point", 1)
    if mode == "custom":
        return point_id in selection.get("point_ids", [])
    return mode == "all"


def selected_line_positions(config: dict, routines_data: dict | None = None) -> list[tuple[int, float]]:
    """Keep selected, unobstructed points in their original spatial order."""
    return [(index, position) for index, position in line_positions(config, routines_data)
            if point_is_selected(index + 1, config) and not is_obstacle(position, config)]


def validate_points_selection(config: dict, routines_data: dict | None = None) -> None:
    """Reject invalid IDs and empty selections before any robot motion."""
    selection = config.get("points_selection", {})
    if not isinstance(selection, dict) or selection.get("mode", "all") not in ("all", "from_point", "custom"):
        raise ValueError("Points selection mode must be all, from_point or custom.")
    count = len(line_positions(config, routines_data))
    mode = selection.get("mode", "all")
    ids = ([selection.get("from_point", 1)] if mode == "from_point" else
           selection.get("point_ids", []) if mode == "custom" else [])
    if not isinstance(ids, list) or any(isinstance(value, bool) or not isinstance(value, int)
                                       or value < 1 or value > count for value in ids):
        raise ValueError(f"Selected point IDs must be integers between 1 and {count}.")
    if mode != "all" and not selected_line_positions(config, routines_data):
        raise ValueError("Select at least one point outside the obstacle.")
