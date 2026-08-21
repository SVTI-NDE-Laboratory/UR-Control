"""Run the complete robot measurement sequence.

Program order:
    1. Move through the configured ``start`` routine.
    2. Perform all configured measurements.
    3. Move through the configured ``end`` routine.

The robot does not move until the operator confirms in the control panel or terminal.
"""

import argparse
import json
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
DATA_ACQUISITION_DIR = PROJECT_ROOT / "data_acquisition_server"

# These folders contain local modules but are not installed Python packages.
# Add them to Python's module search path before importing from them below.
for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR, DATA_ACQUISITION_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from measurement_config import read_measurement_config
from measurement_plan import write_measurement_plan
from measurement_state import write_state
from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
)
from run_measurements import MeasurementUnavailableError, run_measurements
from run_routine import run_routine
from data_acquisition_client import request_data_acquisition
from data_acquisition_server_process import (
    start_data_acquisition_server,
    stop_data_acquisition_server,
)
from timestamped_logging import install_timestamped_tee


# Connection and configuration locations.
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
CONFIG_FILE = CONFIG_DIR / "config.json"

# A joint move counts as complete when every joint is within this many radians.
JOINT_TOLERANCE = 0.01
# Abort waiting for a robot move if it has not completed within this many seconds.
WAIT_TIMEOUT = 30.0
# Home is joint-only in the active routine file. Require every joint to be
# within this many radians of the taught target before permitting any motion.
HOME_JOINT_TOLERANCE = 0.005


def tee_terminal_output(log_path: Path) -> None:
    """Timestamp and mirror subsequent stdout/stderr into ``log_path``."""

    install_timestamped_tee(log_path)


def parse_args() -> argparse.Namespace:
    """Return command-line options for the program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_FILE,
        help="Measurement configuration file (defaults to config/config.json).",
    )
    parser.add_argument(
        "--operator-confirmed",
        action="store_true",
        help="Skip terminal confirmation after confirmation in the control panel.",
    )
    parser.add_argument(
        "--routines-file",
        type=Path,
        default=ROUTINES_FILE,
        help="Waypoint and routine definition file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=CONFIG_DIR,
        help="Folder for config_used.json, state.json, and measurement_plan.json.",
    )
    return parser.parse_args()


def write_used_config(path: Path, config: dict) -> None:
    """Atomically save the effective configuration without changing defaults."""

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


if __name__ == "__main__":
    args = parse_args()

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tee_terminal_output(output_dir / "program.log")

    # Load all operator-defined paths and measurement settings before connecting.
    routines_data = read_routines_file(args.routines_file)
    measurement_config = read_measurement_config(
        args.config, routines_data=routines_data
    )
    state_file = output_dir / "state.json"
    measurement_plan_file = output_dir / "measurement_plan.json"
    write_used_config(output_dir / "config_used.json", measurement_config)
    write_measurement_plan(measurement_plan_file, measurement_config, routines_data)

    # Keep the connection reference for cleanup if startup fails partway through.
    rtde_receive = None
    acquisition_process = None

    try:
        acquire_measurement = None
        if measurement_config["measurement"].get("data_server", True):
            # Start the acquisition service before any robot connection or motion.
            # The launcher returns only after an application-level handshake proves
            # that the expected server and protocol are available.
            acquisition_process, acquisition_config = start_data_acquisition_server(
                output_dir / "data_acquisition_server.log"
            )
            handshake = acquisition_config["handshake"]
            print(
                "Data acquisition handshake confirmed: "
                f"{handshake['server']} protocol {handshake['protocol_version']}."
            )

            def acquire_measurement(payload: dict) -> dict:
                return request_data_acquisition(
                    acquisition_config["host"],
                    acquisition_config["port"],
                    payload,
                    acquisition_config["request_timeout"],
                )
        else:
            print("Data acquisition server disabled by measurement.data_server=false.")

        # Direct terminal runs retain their confirmation. The control panel
        # supplies --operator-confirmed only after its safety dialog is accepted.
        if not args.operator_confirmed:
            input("Press Enter to connect and start the full program, or Ctrl+C to cancel.")

        # Verify that the robot accepts remote commands, then open the RTDE
        # feedback connection used to observe its actual position and state.
        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)
        home = get_waypoint(routines_data, "Home")
        if "q" not in home:
            raise ValueError("The Home waypoint has no joint target for startup verification.")
        write_state(state_file, {"mode": "checking_home"})
        assert_at_home(rtde_receive, home["q"], HOME_JOINT_TOLERANCE)
        print("Startup position verified: robot is at Home.")

        # Move from Home through the configured approach waypoints.
        write_state(state_file, {"mode": "start_routine"})
        run_routine("start", routines_data, ROBOT_IP, rtde_receive, JOINT_TOLERANCE, WAIT_TIMEOUT, False, True)

        # Step along the measurement line and run the measurement procedure.
        write_state(state_file, {"mode": "measurements"})
        run_measurements(
            ROBOT_IP,
            rtde_receive,
            measurement_config,
            state_file,
            routines_data,
            measurement_plan_file,
            acquire_measurement,
        )

        # Return through the configured waypoints to Home. The first move is
        # linear so the tool follows a straight path back to the high pose.
        write_state(state_file, {"mode": "end_routine"})
        run_routine("end", routines_data, ROBOT_IP, rtde_receive,
                    JOINT_TOLERANCE, WAIT_TIMEOUT, False, True)

        # Reaching idle means the complete sequence finished successfully.
        write_state(state_file, {"mode": "idle"})

    except UnsafeStartPositionError as error:
        write_state(
            state_file,
            {
                "mode": "unsafe_start",
                "message": str(error),
            },
        )
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(3)
    except MeasurementUnavailableError as error:
        write_state(
            state_file,
            {
                "mode": "measurement_failed",
                "measurement_index": error.measurement_index,
                "line_position": error.line_position,
                "height_mode": "high",
                "last_measurement_success": False,
                "message": str(error),
            },
        )
        print(f"\n{error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        write_state(state_file, {"mode": "stopped", "reason": "operator cancellation"})
        print("\nProgram cancelled; any active routine or measurement was stopped.")
        raise SystemExit(130)
    except BaseException as error:
        write_state(
            state_file,
            {
                "mode": "error",
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )
        raise
    finally:
        # Always release communication resources, including after Ctrl+C or an
        # exception. This cleanup does not command the robot back to Home.
        if rtde_receive is not None:
            rtde_receive.disconnect()
        stop_data_acquisition_server(acquisition_process)
