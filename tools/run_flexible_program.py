"""Launch the flexible interactive measurement command from the tools folder.

Edit ``ROUTINES_FILE`` below to choose which taught routine file this helper
uses. The flexible command itself is left unchanged.
"""

from pathlib import Path
import runpy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

# Edit this line to choose the routine file used by the flexible program.
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routine_mira.json"

COMMAND_FILE = (
    PROJECT_ROOT
    / "src"
    / "program"
    / "commands"
    / "run_flexible_measurement.py"
)


if __name__ == "__main__":
    command_globals = runpy.run_path(str(COMMAND_FILE), run_name="run_flexible_measurement")
    command_globals["ROUTINES_FILE"] = ROUTINES_FILE
    command_globals["run"]()
