"""Read and validate measurement configuration."""

import json
from pathlib import Path

from line_planner import (
    POINT_TO_POINT,
    high_low_movement,
    line_geometry,
    line_parameters,
    normalize,
    obstacle_interval,
)


def validate_force_config(config: dict) -> None:
    """Validate force settings before any routine can move the robot."""

    measurement = config["measurement"]
    measurement.setdefault("data_server", True)
    contact = measurement["contact_threshold"]
    holding = measurement["holding_force"]
    if contact < 0 or holding < 0:
        raise ValueError("Contact and holding force cannot be negative.")
    if (contact == 0) != (holding == 0):
        raise ValueError(
            "Contact and holding force must either both be zero for simulation "
            "or both be greater than zero."
        )
    if holding < contact:
        raise ValueError("Holding force must be greater than or equal to contact force.")
    if measurement["max_displacement"] <= 0:
        raise ValueError("Maximum displacement must be positive.")
    if not measurement["program_path"].strip():
        raise ValueError("Robot program path cannot be empty.")
    if not isinstance(measurement["data_server"], bool):
        raise ValueError("Data server must be true or false.")
    if "force_step_distance" in measurement and measurement["force_step_distance"] <= 0:
        raise ValueError("Force step distance must be positive.")
    if "force_direction" in measurement:
        normalize(measurement["force_direction"])
    if contact == 0 and holding == 0:
        measurement["simulation"] = True


def validate_measurement_config(
    config: dict, routines_data: dict | None = None
) -> dict:
    """Validate line, obstacle, motion, and force configuration."""

    geometry = line_geometry(config, routines_data)
    high_low_movement(config, routines_data)
    interval = obstacle_interval(config)
    if interval is not None and interval[1] > geometry["length"] + 1e-9:
        raise ValueError("Obstacle end must not exceed the measurement line length.")

    motion = config["motion"]
    if motion["type"].lower() != "l":
        raise ValueError("Measurement motion type must be 'l'.")
    if motion["acceleration"] <= 0 or motion["speed"] <= 0:
        raise ValueError("Measurement acceleration and speed must be positive.")
    validate_force_config(config)
    return geometry


def print_measurement_config_summary(
    config: dict, routines_data: dict | None = None
) -> None:
    """Print the effective measurement geometry and force settings."""

    geometry = validate_measurement_config(config, routines_data)
    parameters = line_parameters(config)
    obstacle = obstacle_interval(config)
    direction, height = high_low_movement(config, routines_data) or (None, None)
    measurement = config["measurement"]
    motion = config["motion"]

    print("Measurement config:")
    if geometry["method"] == POINT_TO_POINT:
        print(
            "  line: method=point_to_point, "
            f"start={geometry['start_name']}, end={geometry['end_name']}, "
            f"measurements={geometry['number_of_measurements']}, "
            f"length={geometry['length']:.6f} m"
        )
        print(
            f"  high-to-low: derived distance={height:.6f} m, "
            f"base-frame direction={direction}"
        )
    else:
        print(
            "  line: method=translation, "
            f"length={geometry['length']} m, increment={geometry['increment']} m, "
            f"direction_start_end={parameters['direction_start_end']} in tool frame"
        )
        if direction is None:
            print("  high-to-low movement: none")
        else:
            print(
                f"  high-to-low: distance={height} m, direction={direction} in tool frame"
            )
    if obstacle is None:
        print("  obstacle: none")
    else:
        print(f"  obstacle: start={obstacle[0]} m, end={obstacle[1]} m")
    print(
        f"  measurement: contact_threshold={measurement['contact_threshold']} N, "
        f"holding_force={measurement['holding_force']} N, "
        f"max_displacement={measurement['max_displacement']} m"
    )
    print(
        f"  measurement: program_path={measurement['program_path']}, "
        f"simulation={measurement['simulation']}, "
        f"data_server={measurement['data_server']}"
    )
    print(
        f"  motion: type={motion['type']}, acceleration={motion['acceleration']}, "
        f"speed={motion['speed']}"
    )


def read_measurement_config(
    path: str | Path,
    verbose: bool = False,
    routines_data: dict | None = None,
) -> dict:
    """Read and validate a measurement configuration file."""

    config = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_measurement_config(config, routines_data)
    if verbose:
        print_measurement_config_summary(config, routines_data)
    return config
