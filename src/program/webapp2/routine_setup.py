"""WebApp2 routine selection and PolyScope import, without commanding the robot."""

import json
import math
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

from .profile import read_object, resolve_path, validate_profile, write_object


class RoutineSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=120)


class RoutineCreation(RoutineSelection):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    script: str = Field(min_length=1, max_length=5_000_000)
    home_to_start: list[str] = Field(min_length=2, max_length=200)
    end_to_home: list[str] = Field(min_length=2, max_length=200)
    additional_waypoints: list[str] = Field(default_factory=lambda: ["p_start_l", "p_end_l"], max_length=200)
    speed: float = Field(2.0, gt=0)
    acceleration: float = Field(0.4, gt=0)
    blend_radius: float = Field(5.0, ge=0)


def routine_directory(profile):
    return profile.paths["routine_file"].parent


def creation_defaults(profile):
    data = read_object(profile.paths["routine_file"])
    routines = {item["name"]: [step["waypoint"] for step in item["steps"]] for item in data["routines"]}
    line = read_object(profile.paths["measurement_defaults"])["line"]
    return {"home_to_start": routines.get("home_to_start", ["Home", "home_to_start1", "home_to_start2", "p_start_h"]),
            "end_to_home": routines.get("end_to_home", list(reversed(routines.get("home_to_end", ["Home", "end_to_home3", "end_to_home2", "end_to_home1", "p_end_h"])))),
            "measurement_waypoints": [line["start_point"], line["end_point"]]}


def checked_filename(filename):
    if not filename.lower().endswith(".json"):
        filename += ".json"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]*\.json", filename, re.IGNORECASE):
        raise ValueError("Use a JSON filename without folders or special characters.")
    if filename.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("That filename is reserved by Windows.")
    return filename


def selected_routine(profile):
    values = read_object(profile.path)
    return resolve_path(values["routine_file"], profile.path.parent)


def validate_routines(data):
    if not isinstance(data.get("waypoints"), dict) or not isinstance(data.get("routines"), list):
        raise ValueError("The routine file must contain waypoints and routines.")
    for name, waypoint in data["waypoints"].items():
        if not isinstance(waypoint, dict) or not any(key in waypoint for key in ("p", "q")):
            raise ValueError(f"Waypoint {name} has no pose or joint coordinates.")
        for key, vector in waypoint.items():
            if key in ("p", "q") and (not isinstance(vector, list) or len(vector) != 6
                                      or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector)):
                raise ValueError(f"Waypoint {name}: {key} needs six finite coordinates.")
    names = set()
    for routine in data["routines"]:
        if not isinstance(routine, dict) or not isinstance(routine.get("name"), str) or not routine["name"].strip():
            raise ValueError("Every routine needs a name.")
        if routine["name"] in names:
            raise ValueError(f"Duplicate routine: {routine['name']}")
        names.add(routine["name"])
        steps = routine.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"Routine {routine['name']} needs at least one step.")
        for index, step in enumerate(steps):
            if not isinstance(step, dict) or step.get("waypoint") not in data["waypoints"]:
                raise ValueError(f"Routine {routine['name']} references an unknown waypoint.")
            motion = step.get("motion", {})
            if not isinstance(motion, dict) or motion.get("type") not in ("j", "l"):
                raise ValueError("Routine motion must be joint (j) or linear (l).")
            target = "q" if motion["type"] == "j" else "p"
            if target not in data["waypoints"][step["waypoint"]]:
                raise ValueError(f"Waypoint {step['waypoint']} has no {target} target for its motion type.")
            for key in ("speed", "acceleration", "blend_radius"):
                value = motion.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (key != "blend_radius" and value == 0):
                    raise ValueError(f"Invalid {key} in routine {routine['name']}.")
            if index == len(steps) - 1 and motion["blend_radius"] != 0:
                raise ValueError("The final waypoint must have zero blend radius.")


def selection_values(profile, path):
    values = read_object(profile.path)
    values["routine_file"] = os.path.relpath(path, profile.path.parent)
    validate_routines(read_object(path))
    validate_profile(profile.path, profile.data_dir, values=values)
    return values


def select_routine(profile, filename):
    directory = routine_directory(profile).resolve()
    if filename not in {path.name for path in directory.glob("*.json") if path.is_file()}:
        raise ValueError("Choose a routine file from the routines directory.")
    path = (directory / filename).resolve()
    if path.parent != directory:
        raise ValueError("The routine file must be in the routines directory.")
    values = selection_values(profile, path)
    write_object(profile.path, values)
    return path


def create_routine(profile, request):
    """Use the existing generator in staging; publish only complete valid output."""
    from create_routines_file import create_routines_file

    filename = checked_filename(request.filename)
    directory = routine_directory(profile)
    destination = directory / filename
    if destination.exists():
        raise FileExistsError("A routine file with that name already exists. Choose a new name.")
    home = [name.strip() for name in request.home_to_start]
    end = [name.strip() for name in request.end_to_home]
    extra = creation_defaults(profile)["measurement_waypoints"]
    if request.additional_waypoints != extra:
        raise ValueError("Measurement waypoints are fixed by the measurement defaults.")
    if any(not name for name in home + end + extra):
        raise ValueError("Waypoint names cannot be empty.")
    if home[0] != "Home" or end[-1] != "Home":
        raise ValueError("Home to start must begin at Home; End to Home must finish at Home.")
    if home[-1] != "p_start_h" or end[0] != "p_end_h":
        raise ValueError("Home to start must finish at p_start_h; End to Home must begin at p_end_h.")
    motion = {"type": "j", "speed": request.speed, "acceleration": request.acceleration,
              "blend_radius": request.blend_radius}

    def steps(names):
        return [{"waypoint": name, "motion": {**motion, "blend_radius": 0.0 if i in (0, len(names) - 1) else request.blend_radius}}
                for i, name in enumerate(names)]

    routines = [{"name": name, "steps": steps(names)} for name, names in (
        ("home_to_start", home), ("start_to_home", list(reversed(home))),
        ("home_to_end", list(reversed(end))), ("end_to_home", end))]
    with TemporaryDirectory(prefix="routine-", dir=profile.data_dir / "runtime") as staging:
        script = Path(staging) / "waypoints.script"
        output = Path(staging) / "routine.json"
        script.write_text(request.script, encoding="utf-8")
        missing = create_routines_file(script, output, routines, additional_waypoint_names=extra)
        if missing:
            raise ValueError("Waypoints not found in the script: " + ", ".join(missing))
        selection_values(profile, output)
        # Exclusive creation never overwrites an existing or active routine file.
        payload = json.dumps(read_object(output), indent=2, allow_nan=False) + "\n"
        created = False
        try:
            with destination.open("x", encoding="utf-8") as stream:
                created = True
                stream.write(payload)
        except BaseException:
            if created:
                destination.unlink(missing_ok=True)
            raise
    return destination
