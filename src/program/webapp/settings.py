"""Paths and constants shared by the web control panel."""

import sys
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = WEBAPP_DIR.parent
PROJECT_ROOT = PROGRAM_DIR.parent.parent
CONFIG_DIR = PROGRAM_DIR / "config"
MIRA_CONFIG_FILE = CONFIG_DIR / "config_mira.json"
SERVER_CONFIG_FILE = CONFIG_DIR / "config_server.json"
HTML_TEMPLATE_FILE = WEBAPP_DIR / "pages" / "configuration.html"
STATIC_DIR = WEBAPP_DIR / "static"
TEMP_CONFIG_FILE = CONFIG_DIR / "config_tmp.json"
COMMANDS_DIR = PROGRAM_DIR / "commands"
MAIN_FILE = COMMANDS_DIR / "run_measurement_sequence.py"
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
    "line_length": "Total Length [mm]",
    "increment": "Increment [mm]",
    "direction_start_end": "Start-to-End Direction [x, y, z]",
    "start": "Start Position [mm]",
    "end": "End Position [mm]",
    "direction_high_low": "High-to-Low Direction [x, y, z]",
    "program_path": "Robot Program Path",
    "contact_threshold": "Contact Threshold [N]",
    "holding_force": "Holding Force [N]",
    "max_displacement": "Maximum Displacement [mm]",
    "simulation": "Simulation",
    "type": "Motion Type (j/l)",
    "acceleration": "Acceleration [mm/s^2]",
    "speed": "Speed [mm/s]",
    "force_step_distance": "Force Step Distance [mm]",
    "force_direction": "Force Direction [x, y, z]",
    "start_point": "Low Start Waypoint",
    "end_point": "Low End Waypoint",
    "number_of_measurements": "Number of Measurements",
    "x_start": "X Start [mm]",
    "x_end": "X End [mm]",
    "offset_y": "Y Offset [mm]",
}
