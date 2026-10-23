"""Browse and read saved runs inside the configured Results directory."""

from pathlib import Path

from measurement_config import read_measurement_config
from line_planner import line_geometry


def results_directory(results: Path, directory: str) -> Path:
    """Resolve a relative folder without following paths outside Results."""
    root = Path(results).resolve()
    folder = (root / directory).resolve()
    if not folder.is_relative_to(root):
        raise ValueError("Choose a folder inside the Results directory.")
    return folder


def configuration_folders(results: Path, directory: str = "") -> dict:
    """List immediate subfolders and identify saved configurations."""
    root = Path(results).resolve()
    folder = results_directory(root, directory)
    if not folder.exists() and folder == root:
        return {"directory": "", "parent": None, "folders": [], "can_load": False}
    if not folder.is_dir():
        raise ValueError("The selected results folder does not exist.")
    folders = []
    for child in sorted(folder.iterdir(), key=lambda path: path.name.casefold()):
        if child.is_dir() and child.resolve().is_relative_to(root):
            folders.append({"name": child.name, "directory": child.relative_to(root).as_posix(),
                            "has_configuration": (child / "config_used.json").is_file()})
    return {"directory": folder.relative_to(root).as_posix(),
            "parent": folder.parent.relative_to(root).as_posix() if folder != root else None,
            "folders": folders, "can_load": (folder / "config_used.json").is_file()}


def read_saved_configuration(results: Path, directory: str, routines: dict) -> dict:
    """Validate a saved run without changing its files or shared defaults."""
    root = Path(results).resolve()
    path = (results_directory(root, directory) / "config_used.json").resolve()
    if not path.is_relative_to(root):
        raise ValueError("The saved configuration must be inside Results.")
    if not path.is_file():
        raise ValueError("This folder has no config_used.json. Select a saved measurement run.")
    config = read_measurement_config(path, routines_data=routines)
    geometry = line_geometry(config, routines)
    if geometry["method"] == "point_to_point":
        # Show the effective saved line, including full-span CLI defaults.
        config["line"].update(increment=geometry["increment"], number_of_measurements=geometry["number_of_measurements"],
                              x_end=geometry["x_end"])
    return config
