"""Run named routines from a loaded routines file."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTINES_DIR = PROJECT_ROOT / "src" / "routines"
if str(ROUTINES_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINES_DIR))

from robot_move import (
    joint_degrees,
    movej,
    movel_pose,
    wait_until_at_joint_target,
    wait_until_at_tcp_target,
)
from robot_connection import assert_robot_running, send_script, stop_robot
from robot_scripts import routine_script, ur_pose
from read_routines import get_routine, get_waypoint

MM_PER_METRE = 1000.0


def linear_motion_for_robot(motion: dict) -> tuple[float, float, float]:
    """Convert a linear routine motion from mm units to UR metre units."""

    return (
        motion["acceleration"] / MM_PER_METRE,
        motion["speed"] / MM_PER_METRE,
        motion["blend_radius"] / MM_PER_METRE,
    )


def blend_radius_for_robot(motion: dict) -> float:
    """Convert a routine blend radius from millimetres to metres."""

    return motion["blend_radius"] / MM_PER_METRE


def run_routine(
    routine_name: str,
    routines_data: dict,
    robot_ip: str,
    rtde_receive,
    joint_tolerance: float,
    wait_timeout: float,
    confirm_each_step: bool,
    verbose: bool,
) -> None:
    """Run a routine using the motion dictionary stored on every step."""

    assert_robot_running(robot_ip)
    try:
        _run_routine(
            routine_name,
            routines_data,
            robot_ip,
            rtde_receive,
            joint_tolerance,
            wait_timeout,
            confirm_each_step,
            verbose,
        )
    except BaseException:
        # This includes KeyboardInterrupt. Never leave a move running merely
        # because its Python caller stopped waiting for it.
        try:
            stop_robot(robot_ip)
        except Exception as stop_error:
            print(f"Warning: robot stop command failed: {stop_error}", file=sys.stderr)
        raise


def _run_routine(
    routine_name: str,
    routines_data: dict,
    robot_ip: str,
    rtde_receive,
    joint_tolerance: float,
    wait_timeout: float,
    confirm_each_step: bool,
    verbose: bool,
) -> None:
    """Implementation separated so the public entry point owns cleanup."""

    routine = get_routine(routines_data, routine_name)

    if verbose:
        print(f"Routine: {routine_name}")

    moves = []
    for step_index, step in enumerate(routine["steps"]):
        waypoint_name = step["waypoint"]
        waypoint = get_waypoint(routines_data, waypoint_name)
        motion = step["motion"]
        motion_type = motion["type"].lower()
        acceleration = motion["acceleration"]
        speed = motion["speed"]
        blend_radius = motion["blend_radius"]

        if acceleration <= 0 or speed <= 0 or blend_radius < 0:
            raise ValueError(f"Routine '{routine_name}', waypoint '{waypoint_name}' has invalid motion values.")
        if step_index == len(routine["steps"]) - 1 and blend_radius != 0:
            raise ValueError(
                f"Routine '{routine_name}' final waypoint '{waypoint_name}' must have blend_radius 0."
            )
        if confirm_each_step and blend_radius != 0:
            raise ValueError(
                f"Routine '{routine_name}' cannot confirm each step while '{waypoint_name}' has a blend radius."
            )

        if motion_type == "l":
            if "p" not in waypoint:
                raise ValueError(f"Waypoint '{waypoint_name}' has no p target for linear motion.")
            robot_acceleration, robot_speed, robot_blend_radius = (
                linear_motion_for_robot(motion)
            )
            if verbose:
                print(
                    f"Moving to {waypoint_name}. Target: {ur_pose(waypoint['p'])} "
                    f"(movel, a={acceleration} mm/s^2, "
                    f"v={speed} mm/s, r={blend_radius} mm)"
                )
            target = waypoint["p"]
        elif motion_type == "j":
            if "q" not in waypoint:
                raise ValueError(f"Waypoint '{waypoint_name}' has no q target for movej.")
            q_target = waypoint["q"]
            if verbose:
                print(
                    f"Moving to {waypoint_name}. Target: {joint_degrees(q_target)} "
                    f"(movej, a={acceleration}, v={speed}, r={blend_radius})"
                )
            target = q_target
            robot_acceleration = acceleration
            robot_speed = speed
            robot_blend_radius = blend_radius_for_robot(motion)
        else:
            raise ValueError(
                f"Routine '{routine_name}', waypoint '{waypoint_name}' has motion type "
                f"'{motion['type']}'. Expected 'j' or 'l'."
            )

        prepared_motion = {
            "type": motion_type,
            "acceleration": robot_acceleration,
            "speed": robot_speed,
            "blend_radius": robot_blend_radius,
        }
        moves.append({"target": target, "motion": prepared_motion})

        if confirm_each_step:
            if motion_type == "l":
                movel_pose(
                    robot_ip,
                    rtde_receive,
                    target,
                    robot_acceleration,
                    robot_speed,
                    wait_timeout,
                )
            else:
                movej(
                    robot_ip,
                    rtde_receive,
                    target,
                    robot_acceleration,
                    robot_speed,
                    joint_tolerance,
                    wait_timeout,
                )
            input("Confirm position, then press Enter for the next move.")

    if confirm_each_step or not moves:
        return

    # With zero blend radius there is no path-continuity advantage in sending
    # one opaque controller program. Execute each move through the verified
    # helpers so a rejected or stalled step is detected immediately.
    if all(move["motion"]["blend_radius"] == 0 for move in moves):
        for move in moves:
            motion = move["motion"]
            if motion["type"] == "l":
                movel_pose(
                    robot_ip,
                    rtde_receive,
                    move["target"],
                    motion["acceleration"],
                    motion["speed"],
                    wait_timeout,
                )
            else:
                movej(
                    robot_ip,
                    rtde_receive,
                    move["target"],
                    motion["acceleration"],
                    motion["speed"],
                    joint_tolerance,
                    wait_timeout,
                )
        return

    send_script(robot_ip, routine_script(moves))
    final_move = moves[-1]
    # The old implementation allowed `wait_timeout` for every individual
    # waypoint. Preserve that allowance now that the routine is sent as one
    # program, while continuously monitoring the robot during the wait.
    routine_timeout = wait_timeout * len(moves)
    if final_move["motion"]["type"] == "j":
        wait_until_at_joint_target(
            rtde_receive,
            final_move["target"],
            joint_tolerance,
            routine_timeout,
            require_target_progress=False,
        )
    else:
        wait_until_at_tcp_target(
            rtde_receive,
            final_move["target"],
            routine_timeout,
            require_target_progress=False,
        )
