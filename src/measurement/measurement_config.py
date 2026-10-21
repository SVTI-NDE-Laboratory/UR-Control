"""Read and validate measurement configuration."""

import json
import math
import os
from pathlib import Path

from line_planner import (
    POINT_TO_POINT,
    high_low_movement,
    line_geometry,
    line_parameters,
    line_method,
    normalize,
    obstacle_interval,
)


DEFAULT_CONFIG_FILE = Path(os.environ.get("UR15_MEASUREMENT_DEFAULTS",
                         Path(__file__).resolve().parents[1] / "program/config/config_default.json"))


def read_default_program_path() -> str:
    """Read the installed force URP path afresh, shared by every stop mode."""

    config = json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))
    value = config.get("measurement", {}).get("program_path")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("config_default.json must contain a nonempty measurement.program_path.")
    return value.strip()


def measurement_stop_method(config: dict) -> str:
    """Resolve timer/client_feedback, accepting former mode names and boolean."""

    measurement = config["measurement"]
    if "stop_method" in measurement:
        method = measurement["stop_method"]
    else:
        legacy = measurement.get("data_server", True)
        if not isinstance(legacy, bool):
            raise ValueError("Legacy data_server must be true or false.")
        method = "client_feedback" if legacy else "timer"
    if isinstance(method, str):
        method = {"time": "timer", "feedback": "client_feedback"}.get(method, method)
    if method not in ("timer", "client_feedback"):
        raise ValueError("Measurement stop_method must be 'timer' or 'client_feedback'.")
    return method


def canonical_config(config: dict) -> dict:
    """Return a copy using the current line and stop-method schema."""

    from copy import deepcopy
    config = deepcopy(config)
    if line_method(config) == POINT_TO_POINT:
        config["line"] = dict(line_parameters(config))
        config["line"].pop("method", None)
    config["measurement"]["stop_method"] = measurement_stop_method(config)
    config["measurement"].setdefault("hold_duration", 0.5)
    config["measurement"].pop("data_server", None)
    return config


def validate_force_config(config: dict) -> None:
    """Validate force settings before any routine can move the robot."""

    measurement = config["measurement"]
    measurement["stop_method"] = measurement_stop_method(config)
    measurement.pop("data_server", None)
    duration = measurement.setdefault("hold_duration", 0.5)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Measurement hold_duration must be positive and finite (seconds).")
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
    obstacle_limit = (geometry["taught_length"] - geometry["x_start"]
                      if geometry["method"] == POINT_TO_POINT else geometry["length"])
    if interval is not None and interval[1] > obstacle_limit + 1e-9:
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
            f"length={geometry['length']:.3f} mm"
        )
        print(
            f"  high-to-low: derived distance={height:.3f} mm, "
            f"base-frame direction={direction}"
        )
        print(
            "  point segment: "
            f"x_start={geometry['x_start']:.3f} mm, "
            f"x_end={geometry['x_end']:.3f} mm, "
            f"y_offset={geometry['offset_y']:.3f} mm"
        )
    else:
        print(
            "  line: method=translation, "
            f"length={geometry['length']} mm, increment={geometry['increment']} mm, "
            f"direction_start_end={parameters['direction_start_end']} in tool frame"
        )
        if direction is None:
            print("  high-to-low movement: none")
        else:
            print(
                f"  high-to-low: distance={height} mm, direction={direction} in tool frame"
            )
    if obstacle is None:
        print("  obstacle: none")
    else:
        origin = geometry.get("x_start", 0.0)
        print(f"  obstacle: start={obstacle[0] + origin} mm, end={obstacle[1] + origin} mm")
    print(
        f"  measurement: contact_threshold={measurement['contact_threshold']} N, "
        f"holding_force={measurement['holding_force']} N, "
        f"max_displacement={measurement['max_displacement']} mm"
    )
    print(
        f"  measurement: program_path={measurement['program_path']}, "
        f"simulation={measurement['simulation']}, "
        f"stop_method={measurement['stop_method']}"
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

    config = canonical_config(json.loads(Path(path).read_text(encoding="utf-8")))
    validate_measurement_config(config, routines_data)
    if verbose:
        print_measurement_config_summary(config, routines_data)
    return config
