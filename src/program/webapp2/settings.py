"""Resolve the selected installation before importing robot or web modules."""

import sys
from pathlib import Path
from .profile import load_profile, activate_environment

ROOT = Path(__file__).resolve().parents[3]
for folder in (ROOT / "src/program", ROOT / "src/robot", ROOT / "src/routines", ROOT / "src/measurement", ROOT / "tools/robot"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

PROFILE = load_profile()
activate_environment(PROFILE)
ROUTINE_FILE = PROFILE.paths["routine_file"]
ROBOT_IP = PROFILE.values["robot_ip"]
RUNTIME = PROFILE.data_dir / "runtime"
POSITION_TOLERANCE = 0.001  # metres
ROTATION_TOLERANCE = 0.01  # radians
JOINT_TOLERANCE = 0.005
MANUAL_MOVE_TIMEOUT = 60.0  # seconds per movement attempt
