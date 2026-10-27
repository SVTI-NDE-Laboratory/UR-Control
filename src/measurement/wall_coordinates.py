"""Installation wall coordinates in millimetres; positive wall Y points upward."""

import json
import math
import os
from contextlib import contextmanager
from pathlib import Path


DEFAULT_WALL_FILE = Path(__file__).resolve().parents[1] / "program/config/wall_coordinates.json"


def read_wall_coordinates(path):
    """Validate the reference and the permitted side of the taught start."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("p_start_l"), dict) or not isinstance(value.get("movement_limits"), dict):
        raise ValueError("Wall coordinates require p_start_l and movement_limits objects.")
    origin, limits = value["p_start_l"], value["movement_limits"]
    if not {"x", "y"} <= origin.keys() or not {"y_direction", "y_max_distance"} <= limits.keys():
        raise ValueError("Specify wall p_start_l x/y and movement_limits y_direction/y_max_distance.")
    for number in (origin["x"], origin["y"], limits["y_max_distance"]):
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError("Wall coordinates and Y maximum distance must be finite numbers (mm).")
    if limits["y_direction"] not in ("up", "down"):
        raise ValueError("Wall y_direction must be 'up' or 'down'.")
    if limits["y_max_distance"] <= 0:
        raise ValueError("Wall y_max_distance must be positive (mm).")
    return value


def wall_reference():
    """Read the selected installation reference; unconfigured library calls stay local."""
    path = os.environ.get("UR15_WALL_COORDINATES")
    return read_wall_coordinates(path) if path else None


@contextmanager
def wall_file(path):
    """Validate a selected profile without retaining another profile's reference."""
    previous = os.environ.get("UR15_WALL_COORDINATES")
    os.environ["UR15_WALL_COORDINATES"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("UR15_WALL_COORDINATES", None)
        else:
            os.environ["UR15_WALL_COORDINATES"] = previous


def local_to_wall(x, y):
    """Add the taught start's wall offset and reverse local Y."""
    reference = wall_reference()
    if reference is None:
        return x, y
    origin = reference["p_start_l"]
    return origin["x"] + x, origin["y"] - y


def wall_to_local(x, y):
    """Resolve absolute wall coordinates into the robot's taught plane."""
    reference = wall_reference()
    if reference is None:
        return x, y
    origin = reference["p_start_l"]
    return x - origin["x"], origin["y"] - y


def tcp_to_wall_xy(pose, start_pose, x_axis, y_axis):
    """Project a base-frame TCP pose onto the wall axes, ignoring normal travel."""
    delta = [pose[index] - start_pose[index] for index in range(3)]
    x = sum(delta[index] * x_axis[index] for index in range(3)) * 1000.0
    y = sum(delta[index] * y_axis[index] for index in range(3)) * 1000.0
    return local_to_wall(x, y)


def wall_limits(taught_length):
    """Return wall X/Y bounds while preserving the taught physical X interval."""
    reference = wall_reference()
    if reference is None:
        return 0.0, taught_length, -400.0, 0.0
    origin = reference["p_start_l"]
    limits = reference["movement_limits"]
    other_y = origin["y"] + limits["y_max_distance"] * (1 if limits["y_direction"] == "up" else -1)
    return origin["x"], origin["x"] + taught_length, min(origin["y"], other_y), max(origin["y"], other_y)


def validate_wall_y(y):
    """Check the installation's permitted side and distance from p_start_l."""
    lower, upper = wall_limits(0)[2:]
    if not math.isfinite(y) or not lower <= y <= upper:
        raise ValueError(f"Wall Y must be between {lower:g} and {upper:g} mm.")
