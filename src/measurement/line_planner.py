"""Pure line/obstacle logic for measurement positions."""


def obstacle_interval(config: dict) -> tuple[float, float] | None:
    """Return the configured obstacle interval, or ``None`` when omitted.

    Start and end are a pair: defining only one is almost certainly a typo and
    is rejected instead of silently disabling collision avoidance.
    """

    obstacle = config.get("obstacle") or {}
    has_start = "start" in obstacle
    has_end = "end" in obstacle
    if has_start != has_end:
        raise ValueError("Obstacle start and end must either both be set or both be omitted.")
    if not has_start:
        return None

    start = obstacle["start"]
    end = obstacle["end"]
    if start > end:
        raise ValueError("Obstacle start must not be greater than obstacle end.")
    return start, end


def high_low_movement(config: dict) -> tuple[list[float], float] | None:
    """Return high/low direction and distance, or ``None`` when omitted."""

    obstacle = config.get("obstacle") or {}
    has_direction = "direction_high_low" in obstacle
    has_distance = "high_low_distance" in obstacle
    if has_direction != has_distance:
        raise ValueError(
            "High-to-low direction and distance must either both be set or both be omitted."
        )
    if obstacle_interval(config) is not None and not has_direction:
        raise ValueError("High-to-low movement must be set when an obstacle exists.")
    if not has_direction:
        return None
    if obstacle["high_low_distance"] <= 0:
        raise ValueError("High-to-low distance must be positive.")
    return obstacle["direction_high_low"], obstacle["high_low_distance"]


def normalize(vector: list[float]) -> list[float]:
    """Return a unit vector in the same direction.

    Used so direction vectors can be configured without caring about magnitude.
    """

    length = sum(value * value for value in vector) ** 0.5
    return [value / length for value in vector]


def scale(vector: list[float], distance: float) -> list[float]:
    """Scale a vector by a distance.

    This converts a unit direction into the actual tool-frame offset to move.
    """

    return [value * distance for value in vector]


def is_obstacle(position: float, config: dict) -> bool:
    """Return whether a line position falls inside the obstacle interval.

    A small tolerance keeps exact boundary points stable despite float rounding.
    """

    tolerance = 1e-9
    interval = obstacle_interval(config)
    if interval is None:
        return False
    start, end = interval
    return start - tolerance <= position <= end + tolerance


def crosses_obstacle(start_position: float, end_position: float, config: dict) -> bool:
    """Return whether a translation segment touches the obstacle interval."""

    interval = obstacle_interval(config)
    if interval is None:
        return False
    obstacle_start, obstacle_end = interval
    segment_start = min(start_position, end_position)
    segment_end = max(start_position, end_position)
    tolerance = 1e-9
    return (
        segment_start <= obstacle_end + tolerance
        and segment_end >= obstacle_start - tolerance
    )


def line_positions(config: dict) -> list[tuple[int, float]]:
    """Return all measurement-line positions as index/distance pairs.

    Positions start at zero and advance by line_increment until line_length.
    """

    line = config["line"]
    positions = []
    index = 0
    position = 0.0

    while position <= line["length"] + 1e-9:
        positions.append((index, position))
        index += 1
        position = index * line["increment"]

    return positions


def next_measurement_step(positions: list[tuple[int, float]], start_step: int, config: dict) -> int | None:
    """Return the next step that is not inside the obstacle.

    Used to jump across obstacle points instead of visiting every obstacle increment.
    """

    for step in range(start_step, len(positions)):
        if not is_obstacle(positions[step][1], config):
            return step

    return None
