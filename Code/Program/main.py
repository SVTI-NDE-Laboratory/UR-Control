"""Main program: start routine, measurements, end routine."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MEASUREMENT_DIR = PROJECT_ROOT / "Code" / "Measurement"
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
ROUTINE_DATA_DIR = PROJECT_ROOT / "Code" / "RoutineData"

for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINE_DATA_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from data_acquisition_server_process import start_data_acquisition_server, stop_data_acquisition_server
from measurement_config import read_measurement_config
from measurement_state import write_state
from read_routines import read_routines_file
from robot_connection import assert_remote_control, get_rtde_receive
from run_measurements import run_measurements
from run_routine import run_routine


ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = PROJECT_ROOT / "Configuration" / "routines.json"
MEASUREMENT_CONFIG_FILE = PROJECT_ROOT / "Configuration" / "measurement_config.json"
STATE_FILE = PROJECT_ROOT / "Configuration" / "state.json"

A = 0.2
V = 4
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    routines_data = read_routines_file(ROUTINES_FILE)
    measurement_config = read_measurement_config(MEASUREMENT_CONFIG_FILE)
    acquisition_server = None
    rtde_receive = None

    try:
        acquisition_server = start_data_acquisition_server(measurement_config)

        input("Press Enter to connect and start the full program, or Ctrl+C to cancel.")
        assert_remote_control(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)

        write_state(STATE_FILE, {"mode": "start_routine"})
        run_routine("start", routines_data, ROBOT_IP, rtde_receive, A, V, JOINT_TOLERANCE, WAIT_TIMEOUT, False, True)

        write_state(STATE_FILE, {"mode": "measurements"})
        run_measurements(ROBOT_IP, rtde_receive, measurement_config, STATE_FILE)

        write_state(STATE_FILE, {"mode": "end_routine"})
        run_routine("end", routines_data, ROBOT_IP, rtde_receive,
                    A, V, JOINT_TOLERANCE, WAIT_TIMEOUT, False, True, linear_first_waypoint=True)

        write_state(STATE_FILE, {"mode": "idle"})

    finally:
        if rtde_receive is not None:
            rtde_receive.disconnect()
        stop_data_acquisition_server(acquisition_server)
