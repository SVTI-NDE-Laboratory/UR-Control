"""Interactively move on the measurement plane and apply force on demand.

The command starts from Home, enters either side of the taught measurement line,
then waits for operator commands:

    move <x_mm> <y_mm>    move linearly to a measurement-frame XY point
    force                 apply one force cycle at the current pose
    pose                  print the current measurement-frame XY estimate
    end                   return to the entry endpoint and run the home routine

All setup values are intentionally hard-coded near the top of the file so this
command can be opened, reviewed, edited, and run directly.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROGRAM_DIR = PROJECT_ROOT / "src" / "program"
CONFIG_DIR = PROGRAM_DIR / "config"
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [PROGRAM_DIR, MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from apply_force import apply_force
from data_acquisition.server_control import AcquisitionControlServer, read_server_config
from line_planner import cross, line_geometry, millimetres_to_metres, normalize
from measurement_config import validate_measurement_config
from measurement_movement import motion_parameters
from measurement_state import write_state
from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
    stop_robot,
)
from robot_move import movel_pose
from run_routine import run_routine


# ---------------------------------------------------------------------------
# Review these hard-coded parameters before running the command.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_wall_275_top.json"
OUTPUT_DIR = CONFIG_DIR

# Choose which side the robot enters from. Use "start" for p_start_l, or "end"
# for p_end_l. The command returns through the same side when `end` is entered.
ENTRY_SIDE = "start"

# If True, the command starts the TCP acquisition-control server, waits for the
# external client to send ALIVE, and during force waits for ISREADY/GO.
DATA_SERVER_ENABLED = True
STANDALONE_FORCE_HOLD_SECONDS = 3.0

FORCE_PROGRAM_PATH = "Inspection/Programs/apply_force_with_server.urp"
CONTACT_THRESHOLD = 140.0
HOLDING_FORCE = 160.0
MAX_DISPLACEMENT = 50.0
SIMULATION = False

LINEAR_ACCELERATION = 100.0
LINEAR_SPEED = 100.0
JOINT_TOLERANCE = 0.01
HOME_JOINT_TOLERANCE = 0.005
WAIT_TIMEOUT = 30.0

HOME_TO_START_ROUTINE = "home_to_start"
START_TO_HOME_ROUTINE = "start_to_home"
HOME_TO_END_ROUTINE = "home_to_end"
END_TO_HOME_ROUTINE = "end_to_home"
LEGACY_START_ROUTINE = "start"
LEGACY_END_ROUTINE = "end"


MEASUREMENT_CONFIG = {
    "line": {
        "method": "point_to_point",
        "parameters": {
            "start_point": "p_start_l",
            "end_point": "p_end_l",
            "spacing_source": "count",
            "number_of_measurements": 2,
            "offset_y": 0.0,
        },
    },
    "motion": {
        "type": "l",
        "acceleration": LINEAR_ACCELERATION,
        "speed": LINEAR_SPEED,
    },
    "measurement": {
        "program_path": FORCE_PROGRAM_PATH,
        "contact_threshold": CONTACT_THRESHOLD,
        "holding_force": HOLDING_FORCE,
        "max_displacement": MAX_DISPLACEMENT,
        "simulation": SIMULATION,
        "data_server": DATA_SERVER_ENABLED,
    },
}


def routine_exists(routines_data: dict[str, Any], routine_name: str) -> bool:
    """Return whether a named routine exists in the loaded routine file."""

    return any(
        routine.get("name") == routine_name
        for routine in routines_data.get("routines", [])
    )


def preferred_routine(
    routines_data: dict[str, Any], preferred_name: str, legacy_name: str
) -> str:
    """Use the newer routine name when present, otherwise keep old files usable."""

    return preferred_name if routine_exists(routines_data, preferred_name) else legacy_name


def measurement_axes(geometry: dict[str, Any]) -> tuple[list[float], list[float]]:
    """Return base-frame X/Y axes for the taught measurement plane."""

    x_axis = geometry["x_axis"]
    try:
        y_axis = normalize(cross(geometry["z_axis"], x_axis))
    except ValueError as error:
        raise ValueError(
            "Cannot resolve measurement Y axis because the high-low direction "
            "and the start-end line are parallel."
        ) from error
    return x_axis, y_axis


def measurement_pose(
    routines_data: dict[str, Any],
    geometry: dict[str, Any],
    x_mm: float,
    y_mm: float,
    height_mode: str = "low",
) -> list[float]:
    """Return a TCP pose at one flexible XY measurement-frame coordinate."""

    if x_mm < -1e-9 or x_mm > geometry["taught_length"] + 1e-9:
        raise ValueError(
            "X must be between 0 and the taught line length "
            f"({geometry['taught_length']:.3f} mm)."
        )

    start_pose = get_waypoint(routines_data, geometry["start_name"])["p"]
    x_axis, y_axis = measurement_axes(geometry)
    target = list(start_pose)
    x_offset = millimetres_to_metres(x_mm)
    y_offset = millimetres_to_metres(y_mm)
    for index in range(3):
        target[index] += x_axis[index] * x_offset + y_axis[index] * y_offset
        if height_mode == "high":
            target[index] += geometry["clearance_offset"][index]
    if height_mode not in {"low", "high"}:
        raise ValueError("height_mode must be 'low' or 'high'.")
    return target


def pose_to_measurement_xy(
    pose: list[float],
    routines_data: dict[str, Any],
    geometry: dict[str, Any],
) -> tuple[float, float]:
    """Project a TCP pose into measurement-frame XY millimetres."""

    start_pose = get_waypoint(routines_data, geometry["start_name"])["p"]
    x_axis, y_axis = measurement_axes(geometry)
    delta = [pose[index] - start_pose[index] for index in range(3)]
    x_mm = sum(delta[index] * x_axis[index] for index in range(3)) * 1000.0
    y_mm = sum(delta[index] * y_axis[index] for index in range(3)) * 1000.0
    return x_mm, y_mm


def endpoint_x(geometry: dict[str, Any], side: str) -> float:
    """Return the X coordinate for the selected endpoint."""

    if side == "start":
        return 0.0
    if side == "end":
        return float(geometry["taught_length"])
    raise ValueError("ENTRY_SIDE must be 'start' or 'end'.")


def start_acquisition_server_if_needed(
    state_file: Path,
    rtde_receive_provider,
) -> tuple[AcquisitionControlServer | None, Any]:
    """Start the acquisition server and wait for ALIVE when enabled."""

    if not DATA_SERVER_ENABLED:
        print("Data acquisition control server disabled.")
        return None, None

    def state_provider() -> dict[str, Any]:
        state: dict[str, Any] = {"mode": "waiting"}
        try:
            state.update(json.loads(state_file.read_text(encoding="utf-8")))
        except Exception:
            pass
        rtde_receive = rtde_receive_provider()
        if rtde_receive is not None:
            try:
                speed = rtde_receive.getActualTCPSpeed()
                state["moving"] = any(abs(value) > 1e-4 for value in speed[:3])
            except Exception as error:
                state["rtde_error"] = str(error)
        return state

    config = read_server_config()
    server = AcquisitionControlServer(
        config["host"],
        int(config["port"]),
        float(config.get("go_timeout", config.get("request_timeout", 8.0))),
        state_provider=state_provider,
    )
    try:
        write_state(
            state_file,
            {
                "mode": "waiting_for_acquisition_client",
                "message": "Waiting for ALIVE from the data acquisition client.",
            },
        )
        server.start()
        print(
            "Waiting for data acquisition client ALIVE on "
            f"{config['host']}:{config['port']}."
        )
        server.wait_for_client_ready(float(config.get("client_ready_timeout", 5.0)))
    except BaseException:
        server.stop()
        raise

    write_state(
        state_file,
        {
            "mode": "acquisition_client_ready",
            "message": "Data acquisition client sent ALIVE.",
        },
    )
    print("Data acquisition client is ready.")
    return server, server.wait_for_go


def standalone_force_hold(context: dict[str, Any]) -> dict[str, Any]:
    """Wait locally when no external acquisition server controls GO."""

    start = time.monotonic()
    time.sleep(STANDALONE_FORCE_HOLD_SECONDS)
    return {"acquisition_time": time.monotonic() - start}


def print_help() -> None:
    """Print the interactive command list."""

    print(
        "\nCommands:\n"
        "  move <x_mm> <y_mm>    move linearly to measurement-frame X/Y\n"
        "  force                 apply one force cycle at the current pose\n"
        "  pose                  print current X/Y estimate\n"
        "  help                  show this help\n"
        "  end                   return to endpoint and run home routine\n"
    )


def run_entry_sequence(
    rtde_receive,
    routines_data: dict[str, Any],
    geometry: dict[str, Any],
    acceleration: float,
    speed: float,
) -> tuple[float, float]:
    """Run home-to-side routine, then descend to the selected low endpoint."""

    side = ENTRY_SIDE.lower()
    if side == "start":
        routine_name = preferred_routine(
            routines_data, HOME_TO_START_ROUTINE, LEGACY_START_ROUTINE
        )
    elif side == "end":
        routine_name = HOME_TO_END_ROUTINE
    else:
        raise ValueError("ENTRY_SIDE must be 'start' or 'end'.")

    run_routine(
        routine_name,
        routines_data,
        ROBOT_IP,
        rtde_receive,
        JOINT_TOLERANCE,
        WAIT_TIMEOUT,
        False,
        True,
    )

    x_mm = endpoint_x(geometry, side)
    print(f"Moving from high side to low endpoint at X={x_mm:.3f} mm, Y=0.000 mm.")
    movel_pose(
        ROBOT_IP,
        rtde_receive,
        measurement_pose(routines_data, geometry, x_mm, 0.0, "low"),
        acceleration,
        speed,
        WAIT_TIMEOUT,
    )
    return x_mm, 0.0


def run_exit_sequence(
    rtde_receive,
    routines_data: dict[str, Any],
    geometry: dict[str, Any],
    acceleration: float,
    speed: float,
) -> None:
    """Return to the selected low endpoint, rise high, and run home routine."""

    side = ENTRY_SIDE.lower()
    x_mm = endpoint_x(geometry, side)
    print(f"Returning linearly to {side} endpoint at X={x_mm:.3f} mm, Y=0.000 mm.")
    movel_pose(
        ROBOT_IP,
        rtde_receive,
        measurement_pose(routines_data, geometry, x_mm, 0.0, "low"),
        acceleration,
        speed,
        WAIT_TIMEOUT,
    )
    print("Moving from low endpoint to high endpoint.")
    movel_pose(
        ROBOT_IP,
        rtde_receive,
        measurement_pose(routines_data, geometry, x_mm, 0.0, "high"),
        acceleration,
        speed,
        WAIT_TIMEOUT,
    )

    routine_name = (
        preferred_routine(routines_data, START_TO_HOME_ROUTINE, LEGACY_END_ROUTINE)
        if side == "start"
        else preferred_routine(routines_data, END_TO_HOME_ROUTINE, LEGACY_END_ROUTINE)
    )
    run_routine(
        routine_name,
        routines_data,
        ROBOT_IP,
        rtde_receive,
        JOINT_TOLERANCE,
        WAIT_TIMEOUT,
        False,
        True,
    )


def run_interactive_loop(
    rtde_receive,
    routines_data: dict[str, Any],
    geometry: dict[str, Any],
    state_file: Path,
    acquire_measurement,
    acceleration: float,
    speed: float,
    initial_xy: tuple[float, float],
) -> None:
    """Wait for operator commands after the entry endpoint has been reached."""

    current_x, current_y = initial_xy
    measurement = MEASUREMENT_CONFIG["measurement"]
    print_help()

    while True:
        write_state(
            state_file,
            {
                "mode": "waiting_for_command",
                "tcp_position": {"X": current_x, "Y": current_y},
                "message": "Waiting for move, force, or end command.",
            },
        )
        command = input("measurement> ").strip()
        if not command:
            continue

        parts = command.split()
        action = parts[0].lower()

        if action == "help":
            print_help()
            continue

        if action == "pose":
            current_x, current_y = pose_to_measurement_xy(
                rtde_receive.getActualTCPPose(), routines_data, geometry
            )
            print(f"Current measurement-frame pose: X={current_x:.3f} mm, Y={current_y:.3f} mm")
            continue

        if action == "move":
            if len(parts) != 3:
                print("Usage: move <x_mm> <y_mm>")
                continue
            try:
                target_x = float(parts[1])
                target_y = float(parts[2])
                target_pose = measurement_pose(
                    routines_data, geometry, target_x, target_y, "low"
                )
            except ValueError as error:
                print(f"Invalid move command: {error}")
                continue

            print(f"Moving linearly to X={target_x:.3f} mm, Y={target_y:.3f} mm.")
            write_state(
                state_file,
                {
                    "mode": "moving",
                    "tcp_position": {"X": target_x, "Y": target_y},
                },
            )
            movel_pose(
                ROBOT_IP,
                rtde_receive,
                target_pose,
                acceleration,
                speed,
                WAIT_TIMEOUT,
            )
            current_x, current_y = target_x, target_y
            print("Move complete.")
            continue

        if action == "force":
            if DATA_SERVER_ENABLED and acquire_measurement is None:
                raise RuntimeError(
                    "Data server is enabled but no acquisition callback is available."
                )
            write_state(
                state_file,
                {
                    "mode": "force",
                    "tcp_position": {"X": current_x, "Y": current_y},
                    "message": "Applying force at current pose.",
                },
            )
            force_reached, timestamp = apply_force(
                ROBOT_IP,
                measurement["program_path"],
                measurement["max_displacement"],
                measurement["contact_threshold"],
                measurement["holding_force"],
                measurement["simulation"],
                acquire_data=(
                    acquire_measurement
                    if DATA_SERVER_ENABLED
                    else standalone_force_hold
                ),
                acquisition_context={
                    "measurement_index": "manual",
                    "x_coordinate": current_x,
                    "y_coordinate": current_y,
                },
                acknowledge_force_hold=True,
            )
            print(f"force_reached={force_reached}, timestamp={timestamp}")
            continue

        if action == "end":
            if len(parts) != 1:
                print("Usage: end")
                continue
            return

        print("Unknown command. Type 'help' for available commands.")


def run() -> None:
    """Run the flexible interactive measurement command."""

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    state_file = OUTPUT_DIR / "state.json"
    routines_data = read_routines_file(ROUTINES_FILE)
    validate_measurement_config(MEASUREMENT_CONFIG, routines_data)
    geometry = line_geometry(MEASUREMENT_CONFIG, routines_data)
    acceleration, speed = motion_parameters(MEASUREMENT_CONFIG)

    home = get_waypoint(routines_data, "Home")
    if "q" not in home:
        raise ValueError("The Home waypoint has no joint target.")

    rtde_receive = None
    control_server = None
    try:
        acquire_measurement = None
        control_server, acquire_measurement = start_acquisition_server_if_needed(
            state_file,
            lambda: rtde_receive,
        )

        input(
            "The robot will move after this confirmation. Confirm the path is "
            "clear, then press Enter to start, or Ctrl+C to cancel."
        )

        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)
        write_state(state_file, {"mode": "checking_home"})
        assert_at_home(rtde_receive, home["q"], HOME_JOINT_TOLERANCE)
        print("Startup position verified: robot is at Home.")

        write_state(state_file, {"mode": "entry_routine"})
        current_xy = run_entry_sequence(
            rtde_receive,
            routines_data,
            geometry,
            acceleration,
            speed,
        )

        run_interactive_loop(
            rtde_receive,
            routines_data,
            geometry,
            state_file,
            acquire_measurement,
            acceleration,
            speed,
            current_xy,
        )

        write_state(state_file, {"mode": "exit_routine"})
        run_exit_sequence(
            rtde_receive,
            routines_data,
            geometry,
            acceleration,
            speed,
        )
        write_state(state_file, {"mode": "idle"})
        print("Flexible measurement command finished at Home.")

    except UnsafeStartPositionError as error:
        write_state(state_file, {"mode": "unsafe_start", "message": str(error)})
        print(f"\n{error}", file=sys.stderr)
        raise SystemExit(3)
    except KeyboardInterrupt:
        write_state(state_file, {"mode": "stopped", "reason": "operator cancellation"})
        print("\nProgram cancelled; stopping any active robot motion.")
        try:
            stop_robot(ROBOT_IP)
        except Exception as stop_error:
            print(f"Warning: robot stop command failed: {stop_error}", file=sys.stderr)
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
        if rtde_receive is not None:
            rtde_receive.disconnect()
        if control_server is not None:
            control_server.stop()


if __name__ == "__main__":
    run()
