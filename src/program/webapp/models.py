"""Typed request bodies accepted by the web API."""

from pathlib import Path

from pydantic import BaseModel


class ConfigurationSubmission(BaseModel):
    """Raw browser fields from the configuration form."""

    fields: dict[str, list[str]]


class MeasurementStartRequest(BaseModel):
    """Operator choices required to start the measurement worker."""

    output_directory: Path
    show_terminal: bool = False
    create_session_folder: bool = True
    operator_confirmed: bool = False


class RoutineFileSelection(BaseModel):
    """Routine file used for point geometry and the measurement run."""

    routine_file: str
