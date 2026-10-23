"""Paths and constants shared by the web control panel."""

import sys
import os
from pathlib import Path


WEBAPP_DIR = Path(__file__).resolve().parent
PROGRAM_DIR = WEBAPP_DIR.parent
PROJECT_ROOT = PROGRAM_DIR.parent.parent
CONFIG_DIR = PROGRAM_DIR / "config"
DEFAULT_CONFIG_FILE = Path(os.environ.get("UR15_MEASUREMENT_DEFAULTS", CONFIG_DIR / "config_default.json"))
SERVER_CONFIG_FILE = DEFAULT_CONFIG_FILE
HTML_TEMPLATE_FILE = WEBAPP_DIR / "pages" / "configuration.html"
STATIC_DIR = WEBAPP_DIR / "static"
TEMP_CONFIG_FILE = (Path(os.environ["UR15_WEBAPP_DATA_DIR"]) / "runtime/config_tmp.json"
                    if "UR15_WEBAPP_DATA_DIR" in os.environ else CONFIG_DIR / "config_tmp.json")
COMMANDS_DIR = PROGRAM_DIR / "commands"
MAIN_FILE = COMMANDS_DIR / "run_measurement_sequence.py"
DEFAULT_OUTPUT_DIR = Path(os.environ.get("UR15_RESULTS_DIR", PROJECT_ROOT / "temporary_data"))
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
ROUTINE_FILES_DIR = ROUTINES_DIR / "routine_files"
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_IP = os.environ.get("UR15_ROBOT_IP", "192.168.3.10")
ROUTINES_FILE = ROUTINE_FILES_DIR / "routine_bam_at_svti.json"
DEFAULT_SELECTED_ROUTINES_FILE = ROUTINE_FILES_DIR / "routine_bam_at_svti.json"
DEFAULT_SELECTED_ROUTINES_FILE = Path(os.environ.get("UR15_ROUTINE_FILE", DEFAULT_SELECTED_ROUTINES_FILE))
HOME_JOINT_TOLERANCE = 0.005

for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


FIELD_LABELS = {
    "hold_duration": "Hold Duration [s]",
    "line_length": "Total Length [mm]",
    "increment": "Step Size [mm]",
    "direction_start_end": "Start-to-End Direction [x, y, z]",
    "start": "Start Position [mm]",
    "end": "End Position [mm]",
    "direction_high_low": "High-to-Low Direction [x, y, z]",
    "program_path": "Robot Program Path",
    "target_force": "Target Force [N]",
    "settling_time": "Settling Time [s]",
    "simulation_program_path": "Simulation Robot Program Path",
    "max_displacement": "Maximum Displacement [mm]",
    "simulation": "Simulation",
    "type": "Motion Type (j/l)",
    "acceleration": "Acceleration [mm/s^2]",
    "speed": "Speed [mm/s]",
    "force_step_distance": "Force Step Distance [mm]",
    "force_direction": "Force Direction [x, y, z]",
    "start_point": "Low Start Waypoint",
    "end_point": "Low End Waypoint",
    "number_of_measurements": "Nb. Points",
    "x_start": "X Start [mm]",
    "x_end": "X End [mm]",
    "offset_y": "Y Offset [mm]",
}
