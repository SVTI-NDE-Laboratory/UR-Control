"""New automatic measurement folders, always beneath the configured Results path."""

import os
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class FolderSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    automatic_folder_name: bool = True
    folder_name: str = Field("", max_length=120)


class MeasurementStartRequest(FolderSelection):
    show_terminal: bool = False
    outside_line_confirmed: bool = False


def measurement_folder(results, name):
    """Allow one portable Windows directory name; reject traversal and collisions."""
    reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if (not name or len(name) > 120 or name != name.strip() or name.endswith(".")
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name in {".", ".."} or name.split(".", 1)[0].upper() in reserved):
        raise ValueError("Enter a folder name without paths or Windows reserved characters/names, and without leading/trailing spaces or a final dot.")
    results = Path(results).resolve()
    folder = results / name
    if os.path.lexists(folder):
        raise FileExistsError(f'The measurements folder "{name}" already exists. Choose a different name; existing results will not be overwritten.')
    return folder
