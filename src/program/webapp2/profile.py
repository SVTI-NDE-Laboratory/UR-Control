"""Persistent per-user installation profiles, independent of the source tree."""

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory


ROOT = Path(__file__).resolve().parents[3]
APP_NAME = "RTM Cobot Studio"


def read_object(path):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON number {value} in {path}")
    value = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def write_object(path, value):
    """Replace a settings file atomically without discarding the old on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            staging = Path(stream.name)
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
        staging.replace(path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def resolve_path(value, base):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Configuration paths must be nonempty strings.")
    path = Path(os.path.expandvars(value)).expanduser()
    return (path if path.is_absolute() else base / path).resolve()


def appdata_directory():
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) if local else Path.home() / "AppData/Local").resolve()


def default_directory():
    override = os.environ.get("UR15_WEBAPP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return appdata_directory() / APP_NAME


def location_file():
    override = os.environ.get("UR15_WEBAPP_LOCATION_FILE")
    return Path(override) if override else default_directory() / "location.json"


def application_directory():
    locator = location_file()
    if locator.is_file():
        return resolve_path(read_object(locator)["data_directory"], locator.parent)
    return default_directory()


def existing_profile(data_dir):
    data_dir = Path(data_dir).resolve()
    preferences = read_object(data_dir / "preferences.json")
    if preferences.get("schema_version") != 1:
        raise ValueError("Unsupported preferences.json schema_version; expected 1.")
    return validate_profile(resolve_path(preferences.get("configuration_path"), data_dir), data_dir)


def prepare_startup(interactive=True):
    """Locate user data before settings imports; never silently replace lost data."""
    migrate_legacy_directory()
    locator = location_file()
    os.environ["UR15_WEBAPP_LOCATION_FILE"] = str(locator)
    data_dir = application_directory()
    if interactive and not (data_dir / "preferences.json").is_file():
        from .dialogs import choose_local_data
        selected = choose_local_data(missing=True)
        if selected is None:
            raise ValueError("Local data selection cancelled. RTM Cobot Studio was not started.")
        if not (selected / "preferences.json").exists():
            if selected.exists() and any(selected.iterdir()):
                raise ValueError("Select a WebApp local data folder or an empty folder.")
            initialize(selected)
        existing_profile(selected)
        write_object(locator, {"data_directory": str(selected)})


def change_data_directory(profile, destination):
    """Select existing data, or copy current data to an empty folder; keep originals."""
    destination = Path(destination).resolve()
    source = profile.data_dir.resolve()
    if destination == source:
        write_object(location_file(), {"data_directory": str(source)})
        return profile
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError("Choose a folder separate from the current local data folder.")
    if not (destination / "preferences.json").exists():
        if destination.exists() and any(destination.iterdir()):
            raise ValueError("Select a WebApp local data folder or an empty folder.")
        copy_local_data(profile, destination)
    candidate = existing_profile(destination)
    write_object(location_file(), {"data_directory": str(destination)})
    return candidate


def copy_local_data(profile, destination):
    """Copy data and rebase internal absolute paths without changing the locator."""
    source = profile.data_dir.resolve()
    destination = Path(destination).resolve()
    shutil.copytree(source, destination, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("location.json"))
    preferences_path = destination / "preferences.json"
    preferences = read_object(preferences_path)
    selected = resolve_path(preferences["configuration_path"], source)
    if selected.is_relative_to(source):
        copied_config = destination / selected.relative_to(source)
        preferences["configuration_path"] = str(copied_config.relative_to(destination))
        values = read_object(copied_config)
        for key in ("routine_file", "measurement_defaults", "acquisition_config",
                    "robot_programs_directory", "results_directory", "routine_scripts_directory"):
            if key not in values:
                continue
            original = resolve_path(values[key], selected.parent)
            if original.is_relative_to(source):
                values[key] = os.path.relpath(destination / original.relative_to(source), copied_config.parent)
        write_object(copied_config, values)
        write_object(preferences_path, preferences)
    return existing_profile(destination)


def migrate_legacy_directory():
    """Adopt the app's new default name once; preserve originals and custom paths."""
    if os.environ.get("UR15_WEBAPP_DATA_DIR") or os.environ.get("UR15_WEBAPP_LOCATION_FILE"):
        return
    destination = default_directory()
    if destination.exists():
        return
    old = appdata_directory() / "UR15 WebApp"
    old_locator = old / "location.json"
    if not old.exists():
        return
    selected = resolve_path(read_object(old_locator)["data_directory"], old) if old_locator.is_file() else old
    if selected.resolve() != old.resolve() or not (selected / "preferences.json").is_file():
        # Keep a custom selection, even when missing, so startup asks to locate it.
        write_object(destination / "location.json", {"data_directory": str(selected)})
        return
    profile = existing_profile(selected)
    # Stage and validate the entire copy before publishing it under the new name.
    # Rebasing uses relative paths, so the validated copy can then be renamed.
    with TemporaryDirectory(prefix=".rtm-cobot-studio-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "data"
        copy_local_data(profile, staged)
        try:
            staged.rename(destination)
        except FileExistsError:
            # Another startup completed migration first; never merge/overwrite.
            existing_profile(destination)


def display_path(path, base):
    try:
        return os.path.relpath(Path(path).resolve(), Path(base).resolve())
    except ValueError:  # A Windows path on another drive has no relative form.
        return str(path)


def initialize(data_dir):
    """Seed an empty data folder once; existing profiles own all their files."""
    data_dir = Path(data_dir)
    preferences = data_dir / "preferences.json"
    if preferences.exists():
        return preferences

    # Missing preferences in a populated folder indicate existing or incomplete
    # user data. Do not repair it by restoring bundled starter files.
    if data_dir.exists() and any(data_dir.iterdir()):
        raise ValueError("Local data folder is not empty and has no preferences.json. Select existing WebApp data or an empty folder.")

    profile = data_dir / "profiles/default"
    sources = [(ROOT / "src/program/config/config_default.json", profile / "measurement_default.json"),
               (ROOT / "src/program/data_acquisition/config_server.json", profile / "acquisition.json")]
    starter = ROOT / "src/program/webapp2/default_profile"
    for name in ("robot_programs", "routine_scripts", "routines"):
        sources.extend((path, profile / name / path.relative_to(starter / name))
                       for path in (starter / name).rglob("*") if path.is_file())
    for source, destination in sources:
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
    config_path = profile / "app_config.json"
    if not config_path.exists():
        write_object(config_path, {
            "schema_version": 1,
            "robot_ip": "192.168.3.10",
            "routine_file": "routines/routine.json",
            "routine_scripts_directory": "routine_scripts",
            "measurement_defaults": "measurement_default.json",
            "acquisition_config": "acquisition.json",
            "robot_programs_directory": "robot_programs",
            "results_directory": "../../results",
            "ui_defaults": {"linear_speed": 50, "linear_acceleration": 100,
                            "joint_speed": 0.05, "joint_acceleration": 0.1,
                            "force": 200, "settling_time": 1.5, "duration": 3},
        })
    if not preferences.exists():
        write_object(preferences, {"schema_version": 1,
                                  "configuration_path": "profiles/default/app_config.json"})
    for name in ("runtime", "logs"):
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    return preferences


@dataclass(frozen=True)
class Profile:
    data_dir: Path
    path: Path
    values: dict
    paths: dict

    @property
    def preferences_path(self):
        return self.data_dir / "preferences.json"

    def worker_environment(self):
        environment = os.environ.copy()
        environment["UR15_WEBAPP_ACTIVE_PROFILE"] = json.dumps({
            "data_dir": str(self.data_dir), "path": str(self.path), "values": self.values,
            "paths": {key: str(value) for key, value in self.paths.items()}}, allow_nan=False)
        return environment


def validate_profile(path, data_dir, *, values=None):
    path = Path(path).resolve()
    values = read_object(path) if values is None else values
    if values.get("schema_version") != 1:
        raise ValueError("Unsupported app_config.json schema_version; expected 1.")
    ip = values.get("robot_ip")
    if not isinstance(ip, str) or not ip.strip() or any(c.isspace() for c in ip):
        raise ValueError("robot_ip must be a nonempty IP address or hostname without spaces.")
    keys = ("routine_file", "measurement_defaults",
            "acquisition_config", "robot_programs_directory", "results_directory")
    paths = {key: resolve_path(values.get(key), path.parent) for key in keys}
    paths["routine_scripts_directory"] = resolve_path(values.get("routine_scripts_directory", "routine_scripts"), path.parent)
    routines = read_object(paths["routine_file"])
    if not isinstance(routines.get("waypoints"), dict) or not isinstance(routines.get("routines"), list):
        raise ValueError("The routine file must contain waypoints and routines.")
    for folder in (ROOT / "src/measurement", ROOT / "src/routines"):
        if str(folder) not in sys.path:
            sys.path.insert(0, str(folder))
    from measurement_config import canonical_config, validate_measurement_config
    for key in ("measurement_defaults",):
        stored = read_object(paths[key])
        if (not all(isinstance(stored.get(section), dict) for section in ("line", "motion"))
                or not isinstance(stored.get("force", stored.get("measurement")), dict)):
            raise ValueError(f"{key} must contain line, force and motion objects.")
        defaults = canonical_config(stored)
        if not isinstance(defaults["measurement"].get("program_path"), str) or not defaults["measurement"]["program_path"].strip():
            raise ValueError(f"{key} must specify force.program_path on the robot controller.")
        for name in ("start_point", "end_point"):
            if defaults["line"].get(name) not in routines["waypoints"]:
                raise ValueError(f"{key}: {name} is missing from the selected routine file.")
        try:
            validate_measurement_config(canonical_config(defaults), routines)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"Invalid {key}: {error}") from error
    acquisition = read_object(paths["acquisition_config"])
    if not isinstance(acquisition.get("host"), str) or type(acquisition.get("port")) is not int or not 1 <= acquisition["port"] <= 65535:
        raise ValueError("Acquisition configuration needs host and port (1–65535).")
    if not paths["robot_programs_directory"].is_dir():
        raise ValueError("robot_programs_directory must be an existing directory.")
    ui = values.get("ui_defaults", {})
    if not isinstance(ui, dict):
        raise ValueError("ui_defaults must be an object.")
    limits = {"linear_speed": 150, "linear_acceleration": 150,
              "joint_speed": 0.5, "joint_acceleration": 0.5,
              "force": float("inf"), "settling_time": float("inf"), "duration": 8}
    import math
    for name, limit in limits.items():
        value = ui.get(name)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value)
                                  or not (0 <= value <= limit) or (name not in ("duration", "settling_time") and value == 0)):
            raise ValueError(f"Invalid ui_defaults.{name}.")
    return Profile(Path(data_dir).resolve(), path, values, paths)


def load_profile(data_dir=None):
    snapshot = os.environ.get("UR15_WEBAPP_ACTIVE_PROFILE") if data_dir is None else None
    if snapshot:
        active = json.loads(snapshot)
        return Profile(Path(active["data_dir"]), Path(active["path"]), active["values"],
                       {key: Path(value) for key, value in active["paths"].items()})
    if data_dir is None:
        migrate_legacy_directory()
    data_dir = (Path(data_dir) if data_dir is not None else application_directory()).resolve()
    preferences = initialize(data_dir)
    values = read_object(preferences)
    if values.get("schema_version") != 1:
        raise ValueError("Unsupported preferences.json schema_version; expected 1.")
    selected = values.get("configuration_path")
    profile = validate_profile(resolve_path(selected, data_dir), data_dir)
    from measurement_config import configuration_file
    defaults = read_object(profile.paths["measurement_defaults"])
    updated = configuration_file(defaults)
    if updated != defaults or list(updated) != list(defaults):
        write_object(profile.paths["measurement_defaults"], updated)
    ui_defaults = profile.values.get("ui_defaults", {})
    if "threshold" in ui_defaults:
        values = {**profile.values, "ui_defaults": {key: value for key, value in ui_defaults.items() if key != "threshold"}}
        values["ui_defaults"].setdefault("settling_time", 1.5)
        write_object(profile.path, values)
        profile = validate_profile(profile.path, data_dir)
    if "routine_scripts_directory" not in profile.values:
        values = {**profile.values, "routine_scripts_directory": "routine_scripts"}
        write_object(profile.path, values)
        profile = validate_profile(profile.path, data_dir)
    return profile


def select_profile(profile, selected):
    candidate = validate_profile(resolve_path(selected, profile.data_dir), profile.data_dir)
    preferences = read_object(profile.preferences_path)
    preferences["configuration_path"] = str(candidate.path)
    write_object(profile.preferences_path, preferences)
    return candidate


def activate_environment(profile):
    """Share resolved paths with legacy modules and child processes."""
    os.environ.setdefault("UR15_WEBAPP_LOCATION_FILE", str(location_file()))
    os.environ["UR15_WEBAPP_DATA_DIR"] = str(profile.data_dir)
    os.environ["UR15_ROBOT_IP"] = profile.values["robot_ip"]
    for key, env in {"measurement_defaults": "UR15_MEASUREMENT_DEFAULTS",
                     "acquisition_config": "UR15_ACQUISITION_CONFIG",
                     "results_directory": "UR15_RESULTS_DIR",
                     "routine_file": "UR15_ROUTINE_FILE"}.items():
        os.environ[env] = str(profile.paths[key])
    # Profile validation may have imported this module before environment setup.
    if "measurement_config" in sys.modules:
        sys.modules["measurement_config"].DEFAULT_CONFIG_FILE = profile.paths["measurement_defaults"]
