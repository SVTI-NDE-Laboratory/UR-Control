"""Compatibility wrapper for the complete measurement sequence command."""

from pathlib import Path
import runpy


COMMAND_FILE = Path(__file__).resolve().parent / "commands" / "run_measurement_sequence.py"


if __name__ == "__main__":
    runpy.run_path(str(COMMAND_FILE), run_name="__main__")
