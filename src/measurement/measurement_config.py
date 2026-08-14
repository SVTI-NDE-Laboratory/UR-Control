"""Read measurement configuration."""

import json
from pathlib import Path

from line_planner import high_low_movement, obstacle_interval


def validate_force_config(config: dict) -> None:
    """Validate force settings before any routine can move the robot."""

    measurement = config["measurement"]
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
    if contact == 0 and holding == 0:
        measurement["simulation"] = True


def print_measurement_config_summary(config: dict) -> None:
    """Print the measurement configuration in a compact form.

    This gives the operator a quick check before the robot starts moving.
    """

    line = config["line"]
    obstacle = obstacle_interval(config)
    high_low = high_low_movement(config)
    measurement = config["measurement"]
    motion = config["motion"]

    print("Measurement config:")
    print(f"  line: length={line['length']} m, increment={line['increment']} m, direction_start_end={line['direction_start_end']} in tool frame")
    if obstacle is None:
        print("  obstacle: none")
    else:
        print(f"  obstacle: start={obstacle[0]} m, end={obstacle[1]} m")
    if high_low is None:
        print("  high-to-low movement: none")
    else:
        direction, distance = high_low
        print(f"  high-to-low: distance={distance} m, direction={direction} in tool frame")
    print(f"  measurement: contact_threshold={measurement['contact_threshold']} N, holding_force={measurement['holding_force']} N, max_displacement={measurement['max_displacement']} m")
    print(f"  measurement: program_path={measurement['program_path']}, simulation={measurement['simulation']}")
    print(f"  motion: type={motion['type']}, acceleration={motion['acceleration']}, speed={motion['speed']}")


def read_measurement_config(path: str | Path, verbose: bool = False) -> dict:
    """Read the before-start measurement configuration.

    If verbose is true, print a short summary of the loaded parameters.
    """

    config = json.loads(Path(path).read_text(encoding="utf-8"))

    # Validate optional obstacle fields even for non-verbose callers.
    obstacle_interval(config)
    high_low_movement(config)
    validate_force_config(config)

    if verbose:
        print_measurement_config_summary(config)

    return config
