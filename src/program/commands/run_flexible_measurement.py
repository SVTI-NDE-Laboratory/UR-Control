"""Interactively move on the measurement plane and apply force on demand.

The command starts from Home, enters either side of the taught measurement line,
then waits for operator commands:

    move <x_mm> <y_mm>    move linearly to a measurement-frame XY point
    force <seconds>       apply default force, hold, then return
    force <newtons> <seconds|manual>
                          apply that force until timeout or stop
    force <contact_n> <holding_n> <seconds|manual>
                          apply separate contact and holding forces
    pose                  print the current measurement-frame XY estimate
    end                   return to the entry endpoint and run the home routine

All setup values are intentionally hard-coded near the top of the file so this
command can be opened, reviewed, edited, and run directly.
"""

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
from line_planner import cross, line_geometry, millimetres_to_metres, normalize
from measurement_config import validate_force_config, validate_measurement_config
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

# Force parameters
FORCE_PROGRAM_PATH = "Inspection/Programs/apply_force_with_server.urp"
CONTACT_THRESHOLD = 140.0
HOLDING_FORCE = 160.0
MAX_DISPLACEMENT = 50.0
SIMULATION = False

# Motion limits: do not touch
LINEAR_ACCELERATION = 100.0
LINEAR_SPEED = 100.0
JOINT_TOLERANCE = 0.01
HOME_JOINT_TOLERANCE = 0.005
WAIT_TIMEOUT = 30.0
MIN_MANUAL_Y = -400.0
MAX_MANUAL_Y = 0.0

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
        "data_server": False,
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
    allow_x_outside_taught_range: bool = False,
) -> list[float]:
    """Return a TCP pose at one flexible XY measurement-frame coordinate."""

    if (
        not allow_x_outside_taught_range
        and (x_mm < -1e-9 or x_mm > geometry["taught_length"] + 1e-9)
    ):
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


def confirm_outside_taught_x(x_mm: float, geometry: dict[str, Any]) -> bool:
    """Ask the operator to confirm an X target outside the taught interval."""

    taught_length = float(geometry["taught_length"])
    if -1e-9 <= x_mm <= taught_length + 1e-9:
        return True
    print(
        "Warning: requested X is outside the taught range "
        f"[0.000, {taught_length:.3f}] mm: X={x_mm:.3f} mm."
    )
    answer = input("Type 'yes' to move there anyway: ").strip().lower()
    return answer == "yes"


def validate_manual_y(y_mm: float) -> None:
    """Reject manual Y targets outside the traditional allowed range."""

    if y_mm > MAX_MANUAL_Y or y_mm < MIN_MANUAL_Y:
        raise ValueError(
            "Y must stay between "
            f"{MIN_MANUAL_Y:.3f} and {MAX_MANUAL_Y:.3f} mm."
        )


def timed_force_hold(duration_seconds: float):
    """Return an acquisition callback that releases force after a local delay."""

    def hold(_context: dict[str, Any]) -> dict[str, Any]:
        start = time.monotonic()
        print(f"Holding force for {duration_seconds:.3f} s.")
        time.sleep(duration_seconds)
        return {"acquisition_time": time.monotonic() - start}

    return hold


def manual_force_hold(_context: dict[str, Any]) -> dict[str, Any]:
    """Block until the operator types stop, then release the force hold."""

    start = time.monotonic()
    print("Force hold active. Type 'stop' and press Enter to return.")
    while True:
        command = input("force> ").strip().lower()
        if command == "stop":
            return {"acquisition_time": time.monotonic() - start}
        print("Type 'stop' to release the force hold.")


def force_hold_callback(args: list[str]):
    """Return the local force-hold callback requested by a force command."""

    if len(args) != 1:
        raise ValueError("Usage: force <seconds> or force manual")
    if args[0].lower() == "manual":
        return manual_force_hold
    try:
        duration = float(args[0])
    except ValueError as error:
        raise ValueError(
            "Force duration must be a number of seconds or 'manual'."
        ) from error
    if duration < 0:
        raise ValueError("Force duration must not be negative.")
    return timed_force_hold(duration)


def force_measurement_settings(args: list[str]) -> tuple[dict[str, Any], Any]:
    """Return measurement settings and hold callback for one force command."""

    measurement = dict(MEASUREMENT_CONFIG["measurement"])
    if len(args) == 1:
        callback = force_hold_callback(args)
    elif len(args) == 2:
        try:
            requested_force = float(args[0])
        except ValueError as error:
            raise ValueError(
                "Usage: force <seconds>, force manual, "
                "force <newtons> <seconds|manual>, or "
                "force <contact_n> <holding_n> <seconds|manual>"
            ) from error
        measurement["contact_threshold"] = requested_force
        measurement["holding_force"] = requested_force
        callback = force_hold_callback(args[1:])
    elif len(args) == 3:
        try:
            contact_threshold = float(args[0])
            holding_force = float(args[1])
        except ValueError as error:
            raise ValueError(
                "Contact and holding force must be numeric newton values."
            ) from error
        measurement["contact_threshold"] = contact_threshold
        measurement["holding_force"] = holding_force
        callback = force_hold_callback(args[2:])
    else:
        raise ValueError(
            "Usage: force <seconds>, force manual, "
            "force <newtons> <seconds|manual>, or "
            "force <contact_n> <holding_n> <seconds|manual>"
        )

    validate_force_config({"measurement": measurement})
    return measurement, callback


def print_help() -> None:
    """Print the interactive command list."""

    print(
        "\nCommands:\n"
        "  move <x_mm> <y_mm>    move linearly to measurement-frame X/Y\n"
        "  force <seconds>       apply default force, hold that long, then return\n"
        "  force manual          apply default force until you type stop\n"
        "  force <N> <seconds>   apply N newtons, hold that long, then return\n"
        "  force <N> manual      apply N newtons until you type stop\n"
        "  force <contact_N> <holding_N> <seconds|manual>\n"
        "                        use separate contact and holding forces\n"
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
                validate_manual_y(target_y)
                allow_x_outside_taught_range = confirm_outside_taught_x(
                    target_x,
                    geometry,
                )
                if not allow_x_outside_taught_range:
                    print("Move cancelled.")
                    continue
                target_pose = measurement_pose(
                    routines_data,
                    geometry,
                    target_x,
                    target_y,
                    "low",
                    allow_x_outside_taught_range=allow_x_outside_taught_range,
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
            try:
                force_measurement, acquire_measurement = force_measurement_settings(
                    parts[1:]
                )
            except ValueError as error:
                print(error)
                continue
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
                force_measurement["program_path"],
                force_measurement["max_displacement"],
                force_measurement["contact_threshold"],
                force_measurement["holding_force"],
                force_measurement["simulation"],
                acquire_data=acquire_measurement,
                acquisition_context={
                    "measurement_index": "manual",
                    "x_coordinate": current_x,
                    "y_coordinate": current_y,
                    "acquisition_label": "local force hold",
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
    try:
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


if __name__ == "__main__":
    run()
