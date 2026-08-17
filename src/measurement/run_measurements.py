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
    next_measurement_step,
    normalize,
    point_pose,
    scale,
)
from measurement_movement import (
    high_to_low,
    low_to_high,
    motion_parameters,
    return_to_start_high,
    translate_along_line,
)
from measurement_state import write_state
from measurement_plan import record_measurement_result
from apply_force import apply_force
from robot_connection import assert_robot_running, stop_robot
from robot_move import ensure_at_tcp_target, translated_tool_target


class MeasurementUnavailableError(RuntimeError):
    """Raised after recovery when force was not found within maximum travel."""

    def __init__(self, measurement_index: int, line_position: float):
        self.measurement_index = measurement_index
        self.line_position = line_position
        super().__init__(
            "Could not complete measurement "
            f"{measurement_index} at {line_position:.3f} m: force threshold was not reached."
        )


def run_measurements(
    robot_ip: str,
    rtde_receive,
    config: dict,
    state_path: str | Path,
    routines_data: dict | None = None,
    measurement_plan_path: str | Path | None = None,
    acquire_data: Callable[[dict], dict] | None = None,
) -> None:
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
        _run_measurements(
            robot_ip,
            rtde_receive,
            config,
            state_path,
            routines_data,
            measurement_plan_path,
            acquire_data,
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
) -> None:
    """Implementation separated so the public entry point owns cleanup."""

    height_mode = "high"
    geometry = line_geometry(config, routines_data)
    positions = line_positions(config, routines_data)
    measurement = config["measurement"]
    traversal_start_pose = rtde_receive.getActualTCPPose()
    step = 0
    measurement_index = 0
    reached_line_position = None

    while step < len(positions):
        # Describe the active step without claiming that its contact position
        # has already been reached.
        index, position = positions[step]
        in_obstacle = is_obstacle(position, config)
        if not in_obstacle:
            measurement_index += 1
        state = {
            "mode": "measurements",
            "measurement_index": measurement_index if not in_obstacle else None,
            "line_position": reached_line_position,
            "height_mode": height_mode,
            "in_obstacle": in_obstacle,
            "last_measurement_success": None,
        }
        write_state(state_path, state)

        if not in_obstacle:
            print(f"\nMeasurement {measurement_index}, position {position:.3f} m")

        # Never measure inside an obstacle: rise if needed, then jump directly
        # to the next valid measurement point while staying high.
        if in_obstacle:
            if height_mode == "low":
                print("Obstacle: move low -> high")
                low_to_high(robot_ip, rtde_receive, config, routines_data, position)
                height_mode = "high"

            next_step = next_measurement_step(positions, step + 1, config)
            if next_step is None:
                print("Obstacle until end of line")
                break

            next_position = positions[next_step][1]
            print(f"Obstacle: jump to next measurement position {next_position:.3f} m")
            translate_along_line(
                robot_ip,
                rtde_receive,
                config,
                next_position - position,
                routines_data,
                next_position,
                "high",
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
                f"at {position:.3f} m: "
                "force threshold was not reached before the distance/time limit. "
                "Returning to p_start_h."
            )
            print(f"\n{message}")

            # The force URP returns to its initial (low) measurement pose.
            # Rise to the safe plane, then undo all line translation so the TCP
            # finishes at p_start_h. Do not continue with the end routine.
            low_to_high(robot_ip, rtde_receive, config, routines_data, position)
            height_mode = "high"
            if geometry["method"] == "point_to_point":
                return_to_start_high(robot_ip, rtde_receive, config, routines_data)
            elif abs(position) > 1e-12:
                translate_along_line(robot_ip, rtde_receive, config, -position)

            write_state(
                state_path,
                {
                    "mode": "measurement_failed",
                    "measurement_index": measurement_index,
                    "line_position": position,
                    "height_mode": height_mode,
                    "in_obstacle": False,
                    "last_measurement_success": False,
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
                if height_mode == "low":
                    print("Path crosses obstacle: move low -> high before translating")
                    low_to_high(robot_ip, rtde_receive, config, routines_data, position)
                    height_mode = "high"

                print(f"Pass obstacle at safe height: translate to {next_position:.3f} m")
                translate_along_line(
                    robot_ip,
                    rtde_receive,
                    config,
                    next_position - position,
                    routines_data,
                    next_position,
                    "high",
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
    if height_mode == "low":
        print("\nEnd of line: move low -> high")
        low_to_high(
            robot_ip,
            rtde_receive,
            config,
            routines_data,
            positions[-1][1],
        )
        height_mode = "high"

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
        },
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
    low_offset = scale(normalize(high_low_direction), high_low_distance)
    start_low_pose = translated_tool_target(traversal_start_pose, low_offset)
    line_offset = scale(normalize(parameters["direction_start_end"]), line_position)
    return translated_tool_target(start_low_pose, line_offset)
