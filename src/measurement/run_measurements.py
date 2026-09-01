"""Coordinate force measurements along a line containing obstacle zones.

The robot must start at the high position ``p_start_h``. Translation mode uses
tool-frame offsets. Point-to-point mode resolves absolute base-frame poses from
taught low start/end waypoints and keeps the start waypoint's orientation.
"""

import sys
from collections.abc import Callable
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import (
    crosses_obstacle,
    high_low_movement,
    is_obstacle,
    line_geometry,
    line_parameters,
    line_positions,
    millimetres_to_metres,
    next_measurement_step,
    normalize,
    obstacle_interval,
    point_pose,
    scale,
)
from measurement_movement import (
    high_to_low,
    low_to_high,
    motion_parameters,
    move_to_zero_y_high,
    move_to_zero_y_low,
    translate_along_line,
)
from measurement_state import write_state
from measurement_plan import record_measurement_result
from apply_force import apply_force
from robot_connection import assert_robot_running, stop_robot
from robot_move import ensure_at_tcp_target, movel_pose, translated_tool_target
from run_routine import run_routine


START_TO_HOME_ROUTINE = "start_to_home"
HOME_TO_END_ROUTINE = "home_to_end"
DEFAULT_JOINT_TOLERANCE = 0.01
DEFAULT_WAIT_TIMEOUT = 30.0


class MeasurementUnavailableError(RuntimeError):
    """Raised after recovery when force was not found within maximum travel."""

    def __init__(self, measurement_index: int, line_position: float):
        self.measurement_index = measurement_index
        self.line_position = line_position
        super().__init__(
            "Could not complete measurement "
            f"{measurement_index} at {line_position:.3f} mm: "
            "force threshold was not reached."
        )


def run_measurements(
    robot_ip: str,
    rtde_receive,
    config: dict,
    state_path: str | Path,
    routines_data: dict | None = None,
    measurement_plan_path: str | Path | None = None,
    acquire_data: Callable[[dict], dict] | None = None,
    routine_joint_tolerance: float = DEFAULT_JOINT_TOLERANCE,
    routine_wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    routine_verbose: bool = True,
) -> str:
    """Measure every valid position along the configured line.

    ``height_mode`` tracks whether the robot is on the safe high plane or the
    low measurement plane. The published line position changes only after the
    exact measurement pose is reached; progress changes after the force result.
    """

    # Reject an obstacle without a safe vertical movement before any robot
    # command is allowed to start.
    line_geometry(config, routines_data)
    high_low_movement(config, routines_data)
    assert_robot_running(robot_ip)
    try:
        return _run_measurements(
            robot_ip,
            rtde_receive,
            config,
            state_path,
            routines_data,
            measurement_plan_path,
            acquire_data,
            routine_joint_tolerance,
            routine_wait_timeout,
            routine_verbose,
        )
    except BaseException:
        # Includes Ctrl+C and robot safety exceptions. Do not attempt recovery
        # motion here: stop in place and let the operator inspect the robot.
        try:
            stop_robot(robot_ip)
        except Exception as stop_error:
            print(f"Warning: robot stop command failed: {stop_error}", file=sys.stderr)
        raise


def _run_measurements(
    robot_ip: str,
    rtde_receive,
    config: dict,
    state_path: str | Path,
    routines_data: dict | None = None,
    measurement_plan_path: str | Path | None = None,
    acquire_data: Callable[[dict], dict] | None = None,
    routine_joint_tolerance: float = DEFAULT_JOINT_TOLERANCE,
    routine_wait_timeout: float = DEFAULT_WAIT_TIMEOUT,
    routine_verbose: bool = True,
) -> str:
    """Implementation separated so the public entry point owns cleanup."""

    height_mode = "high"
    geometry = line_geometry(config, routines_data)
    positions = line_positions(config, routines_data)
    measurement = config["measurement"]
    traversal_start_pose = rtde_receive.getActualTCPPose()
    step = 0
    measurement_index = None
    reached_line_position = None
    finish_side = "end"

    while step < len(positions):
        # Describe the active step without claiming that its contact position
        # has already been reached.
        index, position = positions[step]
        point_id = index + 1
        in_obstacle = is_obstacle(position, config)
        state = {
            "mode": "measurements",
            "measurement_index": point_id if not in_obstacle else None,
            "line_position": reached_line_position,
            "height_mode": height_mode,
            "in_obstacle": in_obstacle,
            "last_measurement_success": None,
        }
        write_state(state_path, state)

        if not in_obstacle:
            measurement_index = point_id
            print(f"\nMeasurement {measurement_index}, position {position:.3f} mm")

        # Never measure inside an obstacle. If the obstacle blocks the first
        # points, startup has already routed to p_end_h; descend to p_end_l
        # before translating back to the first valid measurement.
        if in_obstacle:
            next_step = next_measurement_step(positions, step + 1, config)
            if next_step is None:
                print("Obstacle until end of line")
                if height_mode == "low":
                    finish_side, reached_line_position = move_to_line_side_high(
                        robot_ip,
                        rtde_receive,
                        config,
                        routines_data,
                        position,
                        geometry,
                    )
                    height_mode = "high"
                break

            next_position = positions[next_step][1]
            if step == 0 and height_mode == "high":
                height_mode = enter_line_from_end_high(
                    robot_ip,
                    rtde_receive,
                    config,
                    routines_data,
                    next_position,
                )
            else:
                print(
                    f"Obstacle: route around obstacle to "
                    f"{next_position:.3f} mm"
                )
                height_mode = safe_avoid_obstacle(
                    robot_ip,
                    rtde_receive,
                    config,
                    routines_data,
                    current_position=position,
                    next_position=next_position,
                    current_height_mode=height_mode,
                    routine_joint_tolerance=routine_joint_tolerance,
                    routine_wait_timeout=routine_wait_timeout,
                    routine_verbose=routine_verbose,
                )
            step = next_step
            continue

        # At a valid point, descend to measurement height and run the force URP.
        if height_mode == "high":
            print("Measurement point: move high -> low")
            high_to_low(robot_ip, rtde_receive, config, routines_data, position)
            height_mode = "low"

        state["height_mode"] = height_mode
        target_pose = measurement_target_pose(
            config,
            geometry,
            traversal_start_pose,
            position,
        )
        acceleration, speed = motion_parameters(config)
        ensure_at_tcp_target(
            robot_ip,
            rtde_receive,
            target_pose,
            acceleration,
            speed,
            30.0,
        )
        # Publish the position only after the exact lateral/contact target is
        # verified. This keeps the UI synchronized with the physical robot.
        reached_line_position = position
        state["line_position"] = reached_line_position
        write_state(state_path, state)

        measurement_success, measurement_timestamp = apply_force(
            robot_ip,
            measurement["program_path"],
            measurement["max_displacement"],
            measurement["contact_threshold"],
            measurement["holding_force"],
            measurement["simulation"],
            acquire_data,
            {
                "measurement_index": measurement_index,
                "line_position": position,
            },
            acknowledge_force_hold=measurement.get("data_server", True),
        )
        if measurement_plan_path is not None:
            record_measurement_result(
                measurement_plan_path,
                measurement_index,
                measurement_success,
                measurement_timestamp,
            )
        state["last_measurement_success"] = measurement_success
        write_state(state_path, state)

        if not measurement_success:
            message = (
                f"Could not complete measurement {measurement_index} "
                f"at {position:.3f} mm: "
                "force threshold was not reached before maximum displacement. "
                "Recovering to the safe high waypoint on this side of the obstacle."
            )
            print(f"\n{message}")

            # The force URP returns to its initial (low) measurement pose.
            # Stay on the measurement line, move to the safe side of the
            # obstacle, then rise to the corresponding high waypoint.
            recovery_side, recovery_position = recover_after_force_limit(
                robot_ip,
                rtde_receive,
                config,
                routines_data,
                position,
                geometry,
            )
            height_mode = "high"
            reached_line_position = recovery_position

            write_state(
                state_path,
                {
                    "mode": "measurement_failed",
                    "measurement_index": measurement_index,
                    "line_position": reached_line_position,
                    "height_mode": height_mode,
                    "in_obstacle": False,
                    "last_measurement_success": False,
                    "recovery_side": recovery_side,
                    "message": message,
                },
            )
            raise MeasurementUnavailableError(measurement_index, position)

        # Move to the following valid point. Check the complete movement
        # segment, not only sampled points: an obstacle can lie wholly between
        # two measurement positions.
        if step < len(positions) - 1:
            next_step = next_measurement_step(positions, step + 1, config)
            if next_step is None:
                print("Obstacle until end of line")
                break

            next_position = positions[next_step][1]
            crosses = crosses_obstacle(position, next_position, config)

            if crosses:
                print(
                    f"Pass obstacle through Home detour to "
                    f"{next_position:.3f} mm"
                )
                height_mode = safe_avoid_obstacle(
                    robot_ip,
                    rtde_receive,
                    config,
                    routines_data,
                    current_position=position,
                    next_position=next_position,
                    current_height_mode=height_mode,
                    routine_joint_tolerance=routine_joint_tolerance,
                    routine_wait_timeout=routine_wait_timeout,
                    routine_verbose=routine_verbose,
                )
                step = next_step
                continue

            print("Translate to next line position")
            translate_along_line(
                robot_ip,
                rtde_receive,
                config,
                next_position - position,
                routines_data,
                next_position,
                "low",
            )

        step += 1

    # Always finish at the safe high level, including after the last measure.
    final_zero_y_done = False
    final_position = (
        geometry["length"]
        if geometry["method"] == "point_to_point"
        else positions[-1][1]
    )
    if height_mode == "low":
        current_position = (
            reached_line_position
            if reached_line_position is not None
            else positions[-1][1]
        )
        zero_y_final = geometry["method"] == "point_to_point" and abs(geometry["offset_y"]) > 1e-12
        should_move_to_end = (
            geometry["method"] == "point_to_point"
            and abs(current_position - final_position) > 1e-9
            and not crosses_obstacle(current_position, final_position, config)
        )
        if should_move_to_end:
            print("\nEnd of line: move to the low end-of-line position")
            translate_along_line(
                robot_ip,
                rtde_receive,
                config,
                final_position - current_position,
                routines_data,
                final_position,
                "low",
            )
        elif geometry["method"] == "point_to_point" and abs(current_position - final_position) > 1e-9:
            final_position = current_position
        if zero_y_final:
            print("\nEnd of line: return from Y offset to taught low line")
            move_to_zero_y_low(
                robot_ip,
                rtde_receive,
                config,
                routines_data,
                final_position,
            )
            final_zero_y_done = True
        print("\nEnd of line: move low -> high")
        low_to_high(
            robot_ip,
            rtde_receive,
            config,
            routines_data,
            final_position,
            lateral_offset=not zero_y_final,
        )
        height_mode = "high"
        finish_side = "end"

    if geometry["method"] == "point_to_point":
        if abs(geometry["offset_y"]) > 1e-12 and not final_zero_y_done:
            print("End of line: return from Y offset to taught line")
            move_to_zero_y_high(
                robot_ip,
                rtde_receive,
                config,
                routines_data,
                final_position,
            )

    # Publish a final state so the caller knows traversal has finished.
    write_state(
        state_path,
        {
            "mode": "measurements_done",
            "measurement_index": measurement_index,
            "line_position": reached_line_position,
            "height_mode": height_mode,
            "in_obstacle": False,
            "last_measurement_success": None,
            "finish_side": finish_side,
        },
    )
    return finish_side


def force_failure_recovery_target(
    config: dict,
    geometry: dict,
    line_position: float,
) -> tuple[str, float]:
    """Return the obstacle-side endpoint for force-limit recovery."""

    line_start = 0.0
    line_end = geometry["length"]
    interval = obstacle_interval(config)
    if interval is None:
        distance_to_start = abs(line_position - line_start)
        distance_to_end = abs(line_end - line_position)
        if distance_to_start <= distance_to_end:
            return "start", line_start
        return "end", line_end

    obstacle_start, obstacle_end = interval
    obstacle_midpoint = (obstacle_start + obstacle_end) / 2.0
    if line_position <= obstacle_midpoint:
        return "start", line_start
    return "end", line_end


def taught_endpoint_position(geometry: dict, side: str) -> float:
    """Return the taught endpoint coordinate in effective line-position units."""

    if side == "start":
        return -geometry.get("x_start", 0.0)
    if side == "end":
        return geometry.get("taught_length", geometry["length"]) - geometry.get("x_start", 0.0)
    raise ValueError(f"Unknown line side: {side}")


def move_to_line_side_high(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None,
    current_position: float,
    geometry: dict,
) -> tuple[str, float]:
    """Move low along the measured line to a side endpoint, then move high."""

    side, side_position = force_failure_recovery_target(
        config,
        geometry,
        current_position,
    )
    taught_side_position = taught_endpoint_position(geometry, side)
    high_waypoint = "p_start_h" if side == "start" else "p_end_h"
    print(
        "Obstacle-side return: translate on low measurement line to "
        f"{side} taught endpoint ({taught_side_position:.3f} mm)."
    )

    if abs(taught_side_position - current_position) > 1e-9:
        translate_along_line(
            robot_ip,
            rtde_receive,
            config,
            taught_side_position - current_position,
            routines_data,
            taught_side_position,
            "low",
        )

    if geometry["method"] == "point_to_point" and abs(geometry["offset_y"]) > 1e-12:
        print(
            "Obstacle-side return: remove Y offset at "
            f"{side} taught low endpoint before {high_waypoint}"
        )
        move_to_zero_y_low(
            robot_ip,
            rtde_receive,
            config,
            routines_data,
            taught_side_position,
        )

    print(f"Obstacle-side return: move low -> high to {high_waypoint}")
    low_to_high(
        robot_ip,
        rtde_receive,
        config,
        routines_data,
        taught_side_position,
        lateral_offset=False,
    )
    return side, taught_side_position


def recover_after_force_limit(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None,
    current_position: float,
    geometry: dict,
) -> tuple[str, float]:
    """Recover from a max-displacement force failure to p_start_h or p_end_h."""

    recovery_side, recovery_position = force_failure_recovery_target(
        config,
        geometry,
        current_position,
    )
    high_waypoint = "p_start_h" if recovery_side == "start" else "p_end_h"
    print(
        "Force-limit recovery: move on low line to "
        f"{recovery_side} ({recovery_position:.3f} mm), then to {high_waypoint}."
    )

    return move_to_line_side_high(
        robot_ip,
        rtde_receive,
        config,
        routines_data,
        current_position,
        geometry,
    )


def obstacle_detour_available(routines_data: dict | None) -> bool:
    """Return whether the routine file supports Home detours around obstacles."""

    routine_names = {
        routine.get("name")
        for routine in (routines_data or {}).get("routines", [])
    }
    return {START_TO_HOME_ROUTINE, HOME_TO_END_ROUTINE}.issubset(routine_names)


def enter_line_from_end_high(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None,
    next_position: float,
) -> str:
    """Move p_end_h -> p_end_l, apply any Y offset, then translate on low line."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != "point_to_point":
        raise ValueError("End-side obstacle entry requires point-to-point geometry.")
    taught_end_position = taught_endpoint_position(geometry, "end")

    print("Obstacle route: p_end_h -> p_end_l")
    high_to_low(
        robot_ip,
        rtde_receive,
        config,
        routines_data,
        taught_end_position,
        lateral_offset=False,
    )

    if abs(geometry["offset_y"]) > 1e-12:
        print(
            "Obstacle route: apply Y offset at taught line end "
            f"({taught_end_position:.3f} mm)"
        )
        acceleration, speed = motion_parameters(config)
        movel_pose(
            robot_ip,
            rtde_receive,
            point_pose(geometry, taught_end_position, "low"),
            acceleration,
            speed,
            30.0,
        )

    if abs(next_position - taught_end_position) > 1e-9:
        print(f"Obstacle route: translate on low line to {next_position:.3f} mm")
        translate_along_line(
            robot_ip,
            rtde_receive,
            config,
            next_position - taught_end_position,
            routines_data,
            next_position,
            "low",
        )
    return "low"


def safe_avoid_obstacle(
    robot_ip: str,
    rtde_receive,
    config: dict,
    routines_data: dict | None,
    current_position: float,
    next_position: float,
    current_height_mode: str,
    routine_joint_tolerance: float,
    routine_wait_timeout: float,
    routine_verbose: bool,
) -> str:
    """Route around an obstacle without translating on the high plane."""

    geometry = line_geometry(config, routines_data)
    if geometry["method"] != "point_to_point" or not obstacle_detour_available(routines_data):
        raise ValueError(
            "Obstacle avoidance requires point-to-point geometry and "
            "start_to_home/home_to_end routines."
        )

    if current_height_mode == "high":
        print("Obstacle route: move down to current low line position")
        high_to_low(robot_ip, rtde_receive, config, routines_data, current_position)

    taught_start_position = taught_endpoint_position(geometry, "start")
    if abs(taught_start_position - current_position) > 1e-9:
        print("Obstacle route: measured low line -> p_start_l")
        translate_along_line(
            robot_ip,
            rtde_receive,
            config,
            taught_start_position - current_position,
            routines_data,
            taught_start_position,
            "low",
        )

    if abs(geometry["offset_y"]) > 1e-12:
        print("Obstacle route: return from Y offset to taught low line at p_start_l")
        move_to_zero_y_low(
            robot_ip,
            rtde_receive,
            config,
            routines_data,
            taught_start_position,
        )

    print("Obstacle route: p_start_l -> p_start_h")
    low_to_high(
        robot_ip,
        rtde_receive,
        config,
        routines_data,
        taught_start_position,
        lateral_offset=False,
    )

    print("Obstacle route: p_start_h -> Home")
    run_routine(
        START_TO_HOME_ROUTINE,
        routines_data,
        robot_ip,
        rtde_receive,
        routine_joint_tolerance,
        routine_wait_timeout,
        False,
        routine_verbose,
    )

    print("Obstacle route: Home -> p_end_h")
    run_routine(
        HOME_TO_END_ROUTINE,
        routines_data,
        robot_ip,
        rtde_receive,
        routine_joint_tolerance,
        routine_wait_timeout,
        False,
        routine_verbose,
    )

    return enter_line_from_end_high(
        robot_ip,
        rtde_receive,
        config,
        routines_data,
        next_position,
    )


def measurement_target_pose(
    config: dict,
    geometry: dict,
    traversal_start_pose: list[float],
    line_position: float,
) -> list[float]:
    """Return the nominal low TCP pose for a force measurement."""

    if geometry["method"] == "point_to_point":
        return point_pose(geometry, line_position, "low")

    parameters = line_parameters(config)
    high_low_direction, high_low_distance = high_low_movement(config)
    low_offset = scale(
        normalize(high_low_direction),
        millimetres_to_metres(high_low_distance),
    )
    start_low_pose = translated_tool_target(traversal_start_pose, low_offset)
    line_offset = scale(
        normalize(parameters["direction_start_end"]),
        millimetres_to_metres(line_position),
    )
    return translated_tool_target(start_low_pose, line_offset)
