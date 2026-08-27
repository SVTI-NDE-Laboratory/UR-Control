"""Run the complete robot measurement sequence.

Program order:
    1. Move through the configured ``home_to_start`` routine.
    2. Perform all configured measurements.
    3. Move through the configured ``end_to_home`` routine.

The robot does not move until the operator confirms in the control panel or terminal.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


# Command modules live in src/program/commands, so three parent levels lead to
# the project root. Building paths from this location lets the program run from
# any working directory.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROGRAM_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROGRAM_DIR / "config"
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

# These folders contain local modules but are not installed Python packages.
# Add them to Python's module search path before importing from them below.
for folder in [PROGRAM_DIR, MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from measurement_config import read_measurement_config
from measurement_plan import write_measurement_plan
from measurement_movement import move_to_start_high
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
from data_acquisition.control_server import (
    AcquisitionControlServer,
    start_acquisition_control_server,
)
from data_acquisition.timestamped_logging import install_timestamped_tee


# Connection and configuration locations.
ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_block.json"
CONFIG_FILE = CONFIG_DIR / "config_mira.json"

# A joint move counts as complete when every joint is within this many radians.
JOINT_TOLERANCE = 0.01
# Abort waiting for a robot move if it has not completed within this many seconds.
WAIT_TIMEOUT = 30.0
# Home is joint-only in the active routine file. Require every joint to be
# within this many radians of the taught target before permitting any motion.
HOME_JOINT_TOLERANCE = 0.005
HOME_TO_START_ROUTINE = "home_to_start"
START_TO_HOME_ROUTINE = "start_to_home"
HOME_TO_END_ROUTINE = "home_to_end"
END_TO_HOME_ROUTINE = "end_to_home"
LEGACY_START_ROUTINE = "start"
LEGACY_END_ROUTINE = "end"

AcquireMeasurement = Callable[[dict[str, Any]], dict[str, Any]]
AcquisitionResources = tuple[AcquisitionControlServer | None, AcquireMeasurement | None]


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
        help="Measurement configuration file (defaults to config/config_mira.json).",
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


def prepare_output_directory(args: argparse.Namespace) -> Path:
    """Create the run output folder and start timestamped program logging."""

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    tee_terminal_output(output_dir / "program.log")
    return output_dir


def load_run_inputs(
    args: argparse.Namespace, output_dir: Path
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    """Load routines/configuration and write the effective inputs for this run."""

    routines_data = read_routines_file(args.routines_file)
    measurement_config = read_measurement_config(
        args.config, routines_data=routines_data
    )
    state_file = output_dir / "state.json"
    measurement_plan_file = output_dir / "measurement_plan.json"
    write_used_config(output_dir / "config_used.json", measurement_config)
    write_measurement_plan(measurement_plan_file, measurement_config, routines_data)
    return routines_data, measurement_config, state_file, measurement_plan_file


def read_state_snapshot(state_file: Path) -> dict[str, Any]:
    """Return the latest program state for ALIVE responses."""

    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mode": "starting"}


def start_acquisition_if_enabled(
    measurement_config: dict[str, Any], state_file: Path
) -> AcquisitionResources:
    """Start data acquisition communication when the run configuration needs it."""

    if not measurement_config["measurement"].get("data_server", True):
        print("Data acquisition control server disabled by measurement.data_server=false.")
        return None, None

    control_server, acquisition_config = start_acquisition_control_server(
        state_provider=lambda: read_state_snapshot(state_file)
    )
    print(
        "Data acquisition control server listening on "
        f"{acquisition_config['host']}:{acquisition_config['port']}."
    )

    def acquire_measurement(payload: dict[str, Any]) -> dict[str, Any]:
        return control_server.wait_for_go(payload)

    return control_server, acquire_measurement


def stop_acquisition_resources(control_server: AcquisitionControlServer | None) -> None:
    """Stop the data acquisition control server."""

    if control_server is not None:
        control_server.stop()


def confirm_operator_if_needed(operator_confirmed: bool) -> None:
    """Keep direct terminal runs interactive while web launches skip the prompt."""

    if not operator_confirmed:
        input("Press Enter to connect and start the full program, or Ctrl+C to cancel.")


def verify_robot_startup(routines_data: dict[str, Any], state_file: Path) -> Any:
    """Connect to robot feedback and verify the robot is ready at Home."""

    assert_robot_running(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)
    try:
        home = get_waypoint(routines_data, "Home")
        if "q" not in home:
            raise ValueError(
                "The Home waypoint has no joint target for startup verification."
            )
        write_state(state_file, {"mode": "checking_home"})
        assert_at_home(rtde_receive, home["q"], HOME_JOINT_TOLERANCE)
    except BaseException:
        rtde_receive.disconnect()
        raise

    print("Startup position verified: robot is at Home.")
    return rtde_receive


def routine_exists(routines_data: dict[str, Any], routine_name: str) -> bool:
    """Return whether a named routine is present in loaded routine data."""

    return any(
        routine.get("name") == routine_name
        for routine in routines_data.get("routines", [])
    )


def preferred_routine(
    routines_data: dict[str, Any], preferred_name: str, legacy_name: str
) -> str:
    """Use the new routine name when present, otherwise keep legacy files usable."""

    return preferred_name if routine_exists(routines_data, preferred_name) else legacy_name


def run_robot_sequence(
    rtde_receive,
    routines_data: dict[str, Any],
    measurement_config: dict[str, Any],
    state_file: Path,
    measurement_plan_file: Path,
    acquire_measurement: AcquireMeasurement | None,
) -> None:
    """Run the start routine, measurement traversal, and end routine."""

    write_state(state_file, {"mode": "start_routine"})
    run_routine(
        preferred_routine(routines_data, HOME_TO_START_ROUTINE, LEGACY_START_ROUTINE),
        routines_data,
        ROBOT_IP,
        rtde_receive,
        JOINT_TOLERANCE,
        WAIT_TIMEOUT,
        False,
        True,
    )
    move_to_start_high(ROBOT_IP, rtde_receive, measurement_config, routines_data)

    write_state(state_file, {"mode": "measurements"})
    run_measurements(
        ROBOT_IP,
        rtde_receive,
        measurement_config,
        state_file,
        routines_data,
        measurement_plan_file,
        acquire_measurement,
        JOINT_TOLERANCE,
        WAIT_TIMEOUT,
        True,
    )

    write_state(state_file, {"mode": "end_routine"})
    run_routine(
        preferred_routine(routines_data, END_TO_HOME_ROUTINE, LEGACY_END_ROUTINE),
        routines_data,
        ROBOT_IP,
        rtde_receive,
        JOINT_TOLERANCE,
        WAIT_TIMEOUT,
        False,
        True,
    )

    write_state(state_file, {"mode": "idle"})


def main() -> None:
    """Run the complete measurement sequence command."""

    args = parse_args()
    output_dir = prepare_output_directory(args)
    routines_data, measurement_config, state_file, measurement_plan_file = (
        load_run_inputs(args, output_dir)
    )

    # Keep the connection reference for cleanup if startup fails partway through.
    rtde_receive = None
    control_server = None

    try:
        control_server, acquire_measurement = start_acquisition_if_enabled(
            measurement_config, state_file
        )
        confirm_operator_if_needed(args.operator_confirmed)
        rtde_receive = verify_robot_startup(routines_data, state_file)
        run_robot_sequence(
            rtde_receive,
            routines_data,
            measurement_config,
            state_file,
            measurement_plan_file,
            acquire_measurement,
        )

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
        stop_acquisition_resources(control_server)


if __name__ == "__main__":
    main()
