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
    force_approach_urp = config["force_approach_urp"]
    data_acquisition = config["data_acquisition"]

    print("Measurement config:")
    print(f"  line: length={line['length']} m, increment={line['increment']} m, direction_start_end={line['direction_start_end']} in tool frame")
    print(f"  obstacle: start={obstacle['start']} m, end={obstacle['end']} m")
    print(f"  obstacle: high_low_distance={obstacle['high_low_distance']} m, direction_high_low={obstacle['direction_high_low']} in tool frame")
    print(f"  measurement: target_force={measurement['target_force']} N, max_displacement={measurement['max_displacement']} m")
    print(f"  measurement: acceleration={measurement['acceleration']}, speed={measurement['speed']}")
    print(f"  force_approach_urp: program_name={force_approach_urp['program_name']}")
    print(f"  force_approach_urp: result_host={force_approach_urp['result_host']}, result_port={force_approach_urp['result_port']}, timeout={force_approach_urp['timeout']} s")
    print(f"  data_acquisition: host={data_acquisition['host']}, port={data_acquisition['port']}, timeout={data_acquisition['timeout']} s")


def read_measurement_config(path: str | Path, verbose: bool = False) -> dict:
    """Read the before-start measurement configuration.

    If verbose is true, print a short summary of the loaded parameters.
    """

    config = json.loads(Path(path).read_text(encoding="utf-8"))

    if verbose:
        print_measurement_config_summary(config)

    return config
