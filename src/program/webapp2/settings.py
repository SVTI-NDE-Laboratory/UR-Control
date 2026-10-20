"""Fixed installation settings, intentionally not selectable in the browser."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for folder in (ROOT / "src/program", ROOT / "src/robot", ROOT / "src/routines", ROOT / "src/measurement", ROOT / "tools/robot"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

ROUTINE_FILE = ROOT / "src/routines/routine_files/routine_bam_at_svti.json"
ROBOT_IP = "192.168.3.10"
RUNTIME = ROOT / "temporary_data/webapp2"
POSITION_TOLERANCE = 0.001  # metres
ROTATION_TOLERANCE = 0.01  # radians
JOINT_TOLERANCE = 0.005
MANUAL_MOVE_TIMEOUT = 60.0  # seconds per movement attempt
