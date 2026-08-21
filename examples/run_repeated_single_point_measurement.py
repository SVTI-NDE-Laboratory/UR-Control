"""Move to one hard-coded low point and run repeated force approaches.

The robot may start either at Home or at p_start_h. If it starts at Home, the
configured start routine is run to reach p_start_h. If it already starts at
p_start_h, the start routine is skipped.

No state, plan, or measurement files are written by this example.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MEASUREMENT_DIR = PROJECT_ROOT / "src" / "measurement"
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"

for folder in [MEASUREMENT_DIR, ROBOT_DIR, ROUTINES_DIR]:
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from apply_force import apply_force
from line_planner import line_geometry, point_pose
from measurement_config import validate_measurement_config
from measurement_movement import motion_parameters
from read_routines import get_waypoint, read_routines_file
from robot_connection import (
    UnsafeStartPositionError,
    assert_at_home,
    assert_robot_running,
    get_rtde_receive,
    stop_robot,
)
from robot_move import movel_pose, tcp_target_errors, vector_norm
from run_routine import run_routine


# ---------------------------------------------------------------------------
# Edit the hard-coded parameters in this section.
# ---------------------------------------------------------------------------

ROBOT_IP = "192.168.3.10"
ROUTINES_FILE = ROUTINES_DIR / "routine_files" / "routines_pk-03-prism-a.json"

# Distance from p_start_l along the p_start_l -> p_end_l measurement line.
TARGET_LINE_POSITION = 0.31

FORCE_PROGRAM_PATH = "Inspection/Programs/apply_force_mira.urp"
CONTACT_THRESHOLD = 140.0
HOLDING_FORCE = 160.0
MAX_DISPLACEMENT = 0.05
SIMULATION = False

JOINT_TOLERANCE = 0.01
HOME_JOINT_TOLERANCE = 0.005
TCP_POSITION_TOLERANCE = 0.001
TCP_ROTATION_TOLERANCE = 0.01
TCP_SPEED_TOLERANCE = 0.002
WAIT_TIMEOUT = 30.0

MEASUREMENT_CONFIG = {
    "line": {
        "method": "point_to_point",
        "parameters": {
            "start_point": "p_start_l",
            "end_point": "p_end_l",
            "spacing_source": "count",
            "number_of_measurements": 2,
            "increment": 0.1,
        },
    },
    "motion": {
        "type": "l",
        "acceleration": 0.1,
        "speed": 0.1,
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


def is_at_tcp_pose(rtde_receive, target_pose: list[float]) -> bool:
    """Return whether the TCP is settled at the target pose."""

    actual_pose = rtde_receive.getActualTCPPose()
    position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)
    tcp_speed = vector_norm(rtde_receive.getActualTCPSpeed())
    return (
        position_error <= TCP_POSITION_TOLERANCE
        and rotation_error <= TCP_ROTATION_TOLERANCE
        and tcp_speed <= TCP_SPEED_TOLERANCE
    )


def is_at_home(rtde_receive, home_q: list[float]) -> bool:
    """Return whether the robot is at the taught Home joint position."""

    try:
        assert_at_home(rtde_receive, home_q, HOME_JOINT_TOLERANCE)
    except UnsafeStartPositionError:
        return False
    return True


def prompt_yes_no(question: str) -> bool:
    """Ask a y/n terminal question."""

    while True:
        answer = input(f"{question} [y/n]: ").strip().lower()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer y or n.")


def run() -> None:
    """Run the interactive one-point measurement example."""

    routines_data = read_routines_file(ROUTINES_FILE)
    validate_measurement_config(MEASUREMENT_CONFIG, routines_data)
    geometry = line_geometry(MEASUREMENT_CONFIG, routines_data)
    if TARGET_LINE_POSITION < 0 or TARGET_LINE_POSITION > geometry["length"]:
        raise ValueError(
            "TARGET_LINE_POSITION must be between 0 and the measurement line "
            f"length ({geometry['length']:.6f} m)."
        )
    acceleration, speed = motion_parameters(MEASUREMENT_CONFIG)

    home = get_waypoint(routines_data, "Home")
    if "q" not in home:
        raise ValueError("The Home waypoint has no joint target.")

    p_start_h = get_waypoint(routines_data, "p_start_h")
    if "p" not in p_start_h:
        raise ValueError("The p_start_h waypoint has no TCP pose.")

    target_low_pose = point_pose(geometry, TARGET_LINE_POSITION, "low")
    target_high_pose = point_pose(geometry, TARGET_LINE_POSITION, "high")
    start_low_pose = point_pose(geometry, 0.0, "low")
    start_high_pose = point_pose(geometry, 0.0, "high")

    rtde_receive = None
    try:
        input(
            "Press Enter to connect and run the one-point measurement example, "
            "or Ctrl+C to cancel."
        )

        assert_robot_running(ROBOT_IP)
        rtde_receive = get_rtde_receive(ROBOT_IP)

        if is_at_tcp_pose(rtde_receive, start_high_pose):
            print("Startup position verified: robot is already at p_start_h.")
        elif is_at_home(rtde_receive, home["q"]):
            print("Startup position verified: robot is at Home.")
            print("Running start routine to reach p_start_h.")
            run_routine(
                "start",
                routines_data,
                ROBOT_IP,
                rtde_receive,
                JOINT_TOLERANCE,
                WAIT_TIMEOUT,
                False,
                True,
            )
        else:
            raise UnsafeStartPositionError(
                "Unsafe start prevented: robot must start at Home or p_start_h."
            )

        print(f"Moving to high position at line distance {TARGET_LINE_POSITION:.3f} m.")
        movel_pose(
            ROBOT_IP,
            rtde_receive,
            target_high_pose,
            acceleration,
            speed,
            WAIT_TIMEOUT,
        )

        print("Moving high -> low at the measurement point.")
        movel_pose(
            ROBOT_IP,
            rtde_receive,
            target_low_pose,
            acceleration,
            speed,
            WAIT_TIMEOUT,
        )

        measurement = MEASUREMENT_CONFIG["measurement"]
        while prompt_yes_no("Perform force approach at this point?"):
            force_reached, timestamp = apply_force(
                ROBOT_IP,
                measurement["program_path"],
                measurement["max_displacement"],
                measurement["contact_threshold"],
                measurement["holding_force"],
                measurement["simulation"],
                acknowledge_force_hold=measurement["data_server"],
            )
            print(f"force_reached = {force_reached}, timestamp = {timestamp}")

        print("Returning linearly to p_start_l, then p_start_h.")
        movel_pose(
            ROBOT_IP,
            rtde_receive,
            start_low_pose,
            acceleration,
            speed,
            WAIT_TIMEOUT,
        )
        movel_pose(
            ROBOT_IP,
            rtde_receive,
            start_high_pose,
            acceleration,
            speed,
            WAIT_TIMEOUT,
        )
        print("One-point measurement example finished at p_start_h.")

    except KeyboardInterrupt:
        print("\nProgram cancelled; stopping any active robot motion.")
        try:
            stop_robot(ROBOT_IP)
        except Exception as stop_error:
            print(f"Warning: robot stop command failed: {stop_error}", file=sys.stderr)
        raise SystemExit(130)
    finally:
        if rtde_receive is not None:
            rtde_receive.disconnect()


if __name__ == "__main__":
    run()
