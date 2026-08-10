"""Read measurement configuration."""

import json
from pathlib import Path


def print_measurement_config_summary(config: dict) -> None:
    """Print the measurement configuration in a compact form.

    This gives the operator a quick check before the robot starts moving.
    """

    line = config["line"]
    obstacle = config["obstacle"]
    measurement = config["measurement"]

    print("Measurement config:")
    print(f"  line: length={line['length']} m, increment={line['increment']} m, direction_start_end={line['direction_start_end']} in tool frame")
    print(f"  obstacle: start={obstacle['start']} m, end={obstacle['end']} m")
    print(f"  obstacle: high_low_distance={obstacle['high_low_distance']} m, direction_high_low={obstacle['direction_high_low']} in tool frame")
    print(f"  measurement: contact_threshold={measurement['contact_threshold']} N, holding_force={measurement['holding_force']} N, max_displacement={measurement['max_displacement']} m")
    print(f"  measurement: program_path={measurement['program_path']}, simulation={measurement['simulation']}")
    print(f"  measurement: acceleration={measurement['acceleration']}, speed={measurement['speed']}")


def read_measurement_config(path: str | Path, verbose: bool = False) -> dict:
    """Read the before-start measurement configuration.

    If verbose is true, print a short summary of the loaded parameters.
    """

    config = json.loads(Path(path).read_text(encoding="utf-8"))

    if verbose:
        print_measurement_config_summary(config)

    return config
