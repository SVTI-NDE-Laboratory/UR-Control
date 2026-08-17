"""Paths and constants shared by the web control panel."""

import sys
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = WEBAPP_DIR.parent
PROJECT_ROOT = PROGRAM_DIR.parent.parent
CONFIG_DIR = PROGRAM_DIR / "config"
DEFAULT_CONFIG_FILE = CONFIG_DIR / "config_point_to_point.json"
TRANSLATION_CONFIG_FILE = CONFIG_DIR / "config_translation.json"
POINT_TO_POINT_CONFIG_FILE = CONFIG_DIR / "config_point_to_point.json"
HTML_TEMPLATE_FILE = WEBAPP_DIR / "pages" / "configuration.html"
STATIC_DIR = WEBAPP_DIR / "static"
TEMP_CONFIG_FILE = CONFIG_DIR / "config_tmp.json"
MAIN_FILE = PROGRAM_DIR / "main.py"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "temporary_data"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
ROUTINE_FILES_DIR = ROUTINES_DIR / "routine_files"
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINE_FILES_DIR / "routines_block_diagonal.json"
DEFAULT_SELECTED_ROUTINES_FILE = ROUTINE_FILES_DIR / "routines_block_diagonal.json"
HOME_JOINT_TOLERANCE = 0.005

for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


FIELD_LABELS = {
    "line_length": "Total Length [cm]",
    "increment": "Increment [cm]",
    "direction_start_end": "Start-to-End Direction [x, y, z]",
    "start": "Start Position [cm]",
    "end": "End Position [cm]",
    "high_low_distance": "Safe Height [cm]",
    "direction_high_low": "High-to-Low Direction [x, y, z]",
    "program_path": "Robot Program Path",
    "contact_threshold": "Contact Threshold [N]",
    "holding_force": "Holding Force [N]",
    "max_displacement": "Maximum Displacement [cm]",
    "simulation": "Simulation",
    "type": "Motion Type (j/l)",
    "acceleration": "Acceleration [m/s²]",
    "speed": "Speed [m/s]",
    "force_step_distance": "Force Step Distance [cm]",
    "force_direction": "Force Direction [x, y, z]",
    "start_point": "Low Start Waypoint",
    "end_point": "Low End Waypoint",
    "number_of_measurements": "Number of Measurements",
}

# The program and JSON files use metres. These fields are shown in centimetres.
CENTIMETRE_FIELDS = {
    "line_length",
    "increment",
    "start",
    "end",
    "high_low_distance",
    "max_displacement",
    "force_step_distance",
}
