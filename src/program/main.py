"""Run the complete robot measurement sequence.

Program order:
    1. Move through the configured ``start`` routine.
    2. Perform all configured measurements.
    3. Move through the configured ``end`` routine.

The robot does not move until the operator confirms in the terminal.
"""

import sys
from pathlib import Path


# ``main.py`` is in src/program, so two parent levels lead to the project root.
# Building paths from this location lets the program run from any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PROGRAM_DIR / "config"
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

# These folders contain local modules but are not installed Python packages.
# Add them to Python's module search path before importing from them below.
for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from measurement_config import read_measurement_config
from measurement_state import write_state
from read_routines import read_routines_file
from robot_connection import assert_remote_control, get_rtde_receive
from run_measurements import run_measurements
from run_routine import run_routine


# Connection and configuration locations.
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"

# Motion and waiting parameters used by the start and end routines.
# For movej: A is rad/s^2 and V is rad/s.
# The first end-routine move is a movel, where the same A and V instead mean
# m/s^2 and m/s. Confirm that these values are safe for both kinds of motion.
A = 0.2
V = 4
# A joint move counts as complete when every joint is within this many radians.
JOINT_TOLERANCE = 0.01
# Abort waiting for a robot move if it has not completed within this many seconds.
WAIT_TIMEOUT = 30.0


if __name__ == "__main__":
    # Load all operator-defined paths and measurement settings before connecting.
    routines_data = read_routines_file(ROUTINES_FILE)
    measurement_config = read_measurement_config(CONFIG_FILE)

    # Keep the connection reference for cleanup if startup fails partway through.
    rtde_receive = None

    try:
        # This is the final operator-controlled pause before any robot command.
        input("Press Enter to connect and start the full program, or Ctrl+C to cancel.")

        # Verify that the robot accepts remote commands, then open the RTDE
        # feedback connection used to observe its actual position and state.
        assert_remote_control(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)

        # Move from Home through the configured approach waypoints.
        write_state(STATE_FILE, {"mode": "start_routine"})
        run_routine("start", routines_data, ROBOT_IP, rtde_receive, A, V, JOINT_TOLERANCE, WAIT_TIMEOUT, False, True)

        # Step along the measurement line and run the measurement procedure.
        write_state(STATE_FILE, {"mode": "measurements"})
        run_measurements(ROBOT_IP, rtde_receive, measurement_config, STATE_FILE)

        # Return through the configured waypoints to Home. The first move is
        # linear so the tool follows a straight path back to the high pose.
        write_state(STATE_FILE, {"mode": "end_routine"})
        run_routine("end", routines_data, ROBOT_IP, rtde_receive,
                    A, V, JOINT_TOLERANCE, WAIT_TIMEOUT, False, True, linear_first_waypoint=True)

        # Reaching idle means the complete sequence finished successfully.
        write_state(STATE_FILE, {"mode": "idle"})

    finally:
        # Always release communication resources, including after Ctrl+C or an
        # exception. This cleanup does not command the robot back to Home.
        if rtde_receive is not None:
            rtde_receive.disconnect()
