"""Read and validate measurement configuration."""

import json
import math
import os
from pathlib import Path

from wall_coordinates import local_to_wall, wall_reference, wall_limits

from line_planner import (
    POINT_TO_POINT,
    high_low_movement,
    line_geometry,
    line_parameters,
    line_method,
    normalize,
    obstacle_interval,
    validate_points_selection,
)


DEFAULT_CONFIG_FILE = Path(os.environ.get("UR15_MEASUREMENT_DEFAULTS",
                         Path(__file__).resolve().parents[1] / "program/config/config_default.json"))


def read_default_program_path(simulation: bool = False) -> str:
    """Read the selected installed force URP path from the current defaults."""
    config = canonical_config(json.loads(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")))
    measurement = normalize_force_settings(config.get("measurement", {}))
    key = "simulation_program_path" if simulation else "program_path"
    value = measurement.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Measurement defaults must contain a nonempty force.{key}.")
    return value.strip()


def normalize_force_settings(measurement: dict) -> dict:
    """Return one target force, settling delay, and separate real/simulation paths."""
    measurement = dict(measurement)
    if "target_force" not in measurement:
        target = measurement.get("holding_force", measurement.get("contact_threshold", 200.0))
        if target == 0 and measurement.get("contact_threshold", 0) == 0:
            measurement["simulation"] = True
            target = 200.0
        measurement["target_force"] = target
    measurement.pop("contact_threshold", None)
    measurement.pop("holding_force", None)
    measurement.setdefault("settling_time", 1.5)
    measurement.setdefault("simulation", False)
    program = measurement.get("program_path", "")
    directory = program.rsplit("/", 1)[0] + "/" if isinstance(program, str) and "/" in program else ""
    measurement.setdefault("simulation_program_path", directory + "apply_force_simulation.urp")
    return measurement


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
    if "force" in config:
        config["measurement"] = config.pop("force")
    if "points_selections" in config:
        config["points_selection"] = config.pop("points_selections")
    if line_method(config) == POINT_TO_POINT:
        config["line"] = dict(line_parameters(config))
        config["line"].pop("method", None)
    config["measurement"] = normalize_force_settings(config["measurement"])
    config["measurement"]["stop_method"] = measurement_stop_method(config)
    config["measurement"].setdefault("hold_duration", 0.5)
    config["measurement"].pop("data_server", None)
    # Keep obstacle settings available while presence controls path exclusions.
    obstacle = config.get("obstacle") or {}
    present = obstacle.get("present", bool(obstacle))
    width = obstacle.get("width", config.get("obstacle_width", 200.0))
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
        raise ValueError("Obstacle width must be positive and finite (mm).")
    position = obstacle.get("position", (obstacle["start"] + obstacle["end"]) / 2.0
                            if "start" in obstacle and "end" in obstacle else width / 2.0)
    if isinstance(position, bool) or not isinstance(position, (int, float)) or not math.isfinite(position):
        raise ValueError("Obstacle position must be a finite number (mm).")
    if not isinstance(present, bool):
        raise ValueError("Obstacle present must be true or false.")
    # Preserve explicit bounds in imported interval configurations.
    if "position" not in obstacle and "start" in obstacle and "end" in obstacle:
        width = obstacle["end"] - obstacle["start"]
    obstacle.update(present=present, width=width, position=position)
    config["obstacle"] = obstacle
    config["obstacle_width"] = width
    if "position" in obstacle:
        obstacle.update(start=position - width / 2.0, end=position + width / 2.0)
    # Convert archived local coordinates once, preserving their physical positions.
    reference = wall_reference()
    if reference is not None and line_method(config) == POINT_TO_POINT and config["line"].get("coordinate_system") != "wall":
        line = config["line"]
        for key in ("x_start", "offset_x", "x_end"):
            if key in line and not (key == "x_end" and line[key] == 0 and line.get("auto_fit", True)):
                line[key] = local_to_wall(line[key], 0.0)[0]
        if line.get("x_end") == 0 and line.get("auto_fit", True):
            line.pop("x_end")
        line["offset_y"] = local_to_wall(0.0, line.get("offset_y", 0.0))[1]
        for key in ("position", "start", "end"):
            obstacle[key] = local_to_wall(obstacle[key], 0.0)[0]
        line["coordinate_system"] = "wall"
    return config


def configuration_file(config: dict) -> dict:
    """Return the ordered JSON schema used by defaults and saved run files."""
    config = canonical_config(config)
    line = {({"increment": "steps", "number_of_measurements": "nb_points"}.get(key, key)): value
            for key, value in config["line"].items()}
    if "spacing_source" in line:
        line["spacing_source"] = {"increment": "steps", "count": "nb_points"}.get(line["spacing_source"], line["spacing_source"])
    obstacle = config["obstacle"]
    force_keys = ("program_path", "target_force", "settling_time", "max_displacement",
                  "stop_method", "hold_duration", "simulation", "simulation_program_path")
    force = {key: config["measurement"][key] for key in force_keys if key in config["measurement"]}
    force.update({key: value for key, value in config["measurement"].items() if key not in force})
    result = {
        "line": line,
        "obstacle": {key: obstacle[key] for key in ("present", "width", "position", "start", "end")},
        "points_selections": config.get("points_selection", {"mode": "all", "from_point": 1, "point_ids": []}),
        "force": force,
        "motion": config["motion"],
    }
    # Retain optional planning fields outside the standard sections.
    result.update({key: value for key, value in config.items()
                   if key not in {"line", "obstacle", "obstacle_width", "points_selection", "measurement", "motion"}})
    return result


def installation_defaults(config: dict, routines_data: dict) -> dict:
    """Keep installation defaults aligned when the wall reference is edited."""
    from copy import deepcopy

    defaults = canonical_config(config)
    reference = wall_reference()
    if reference is None or line_method(defaults) != POINT_TO_POINT:
        return defaults

    line = defaults["line"]
    previous = line.get("wall_reference")

    def shifted_defaults(previous_origin):
        candidate = deepcopy(defaults)
        candidate_line = candidate["line"]
        origin = reference["p_start_l"]
        delta_x = origin["x"] - previous_origin["x"]
        delta_y = origin["y"] - previous_origin["y"]

        # Preserve the taught-relative X section and obstacle location.
        for key in ("x_start", "offset_x", "x_end"):
            if key in candidate_line:
                candidate_line[key] += delta_x
        for key in ("position", "start", "end"):
            candidate["obstacle"][key] += delta_x

        # Keep the Y displacement, bounded by the newly configured side/range.
        lower, upper = wall_limits(0)[2:]
        y = candidate_line.get("offset_y", previous_origin["y"]) + delta_y
        candidate_line["offset_y"] = min(upper, max(lower, y))
        return candidate

    if previous is not None and previous != reference:
        defaults = shifted_defaults(previous["p_start_l"])

    # Wall defaults saved without reference metadata may still use the zero
    # origin. Adopt the new origin only when the existing defaults are invalid
    # and the translated defaults pass the complete measurement validation.
    elif previous is None and reference["p_start_l"] != {"x": 0, "y": 0}:
        try:
            validate_measurement_config(defaults, routines_data)
        except ValueError as original_error:
            candidate = shifted_defaults({"x": 0.0, "y": 0.0})
            try:
                validate_measurement_config(candidate, routines_data)
            except ValueError:
                raise original_error
            defaults = candidate

    defaults["line"]["wall_reference"] = deepcopy(reference)
    return defaults


def validate_force_config(config: dict) -> None:
    """Validate force settings before any routine can move the robot."""

    measurement = config["measurement"]
    measurement["stop_method"] = measurement_stop_method(config)
    measurement.pop("data_server", None)
    duration = measurement.setdefault("hold_duration", 0.5)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Measurement hold_duration must be positive and finite (seconds).")
    normalized = normalize_force_settings(measurement)
    measurement.clear()
    measurement.update(normalized)
    for key in ("target_force", "max_displacement"):
        value = measurement[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"Measurement {key} must be positive and finite.")
    delay = measurement["settling_time"]
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
        raise ValueError("Measurement settling_time must be nonnegative and finite (seconds).")
    if not isinstance(measurement["simulation"], bool):
        raise ValueError("Measurement simulation must be true or false.")
    for key in ("program_path", "simulation_program_path"):
        value = measurement.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Measurement {key} must be a nonempty robot program path.")
    if "force_step_distance" in measurement and measurement["force_step_distance"] <= 0:
        raise ValueError("Force step distance must be positive.")
    if "force_direction" in measurement:
        normalize(measurement["force_direction"])


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
    width = config.get("obstacle_width", 200.0)
    if isinstance(width, bool) or not isinstance(width, (int, float)) or not math.isfinite(width) or width <= 0:
        raise ValueError("Obstacle width must be positive and finite (mm).")
    validate_points_selection(config, routines_data)
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
            f"x_start={local_to_wall(geometry['x_start'], 0.0)[0]:.3f} mm, "
            f"x_end={local_to_wall(geometry['x_end'], 0.0)[0]:.3f} mm, "
            f"y_position={local_to_wall(0.0, geometry['offset_y'])[1]:.3f} mm"
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
        origin = local_to_wall(geometry.get("x_start", 0.0), 0.0)[0]
        print(f"  obstacle: start={obstacle[0] + origin} mm, end={obstacle[1] + origin} mm")
    print(
        f"  measurement: target_force={measurement['target_force']} N, "
        f"settling_time={measurement['settling_time']} s, "
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
