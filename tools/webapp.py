"""Launch the web control panel from the tools folder."""

from pathlib import Path
import runpy
import sys


WEBAPP_DIR = Path(__file__).resolve().parents[1] / "src" / "program" / "webapp"
WEBAPP_FILE = WEBAPP_DIR / "app.py"


if __name__ == "__main__":
    if str(WEBAPP_DIR) not in sys.path:
        sys.path.insert(0, str(WEBAPP_DIR))
    runpy.run_path(str(WEBAPP_FILE), run_name="__main__")
