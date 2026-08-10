"""Pure line/obstacle logic for measurement positions."""


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
    obstacle = config["obstacle"]
    return obstacle["start"] - tolerance <= position <= obstacle["end"] + tolerance


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
