"""Coordinate force measurements along a line containing obstacle zones.

The robot must start at the high position ``p_start_h``. At each valid line
position it moves down, runs ``apply_force``, and records the result. Obstacle
zones are crossed at the safe high level. All translations use the tool frame.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import (
    crosses_obstacle,
    high_low_movement,
    is_obstacle,
    line_positions,
    next_measurement_step,
)
from measurement_movement import high_to_low, low_to_high, translate_along_line
from measurement_state import write_state
from apply_force import apply_force
from robot_connection import assert_robot_running, stop_robot


class MeasurementUnavailableError(RuntimeError):
    """Raised after recovery when force was not found within maximum travel."""

    def __init__(self, line_index: int, line_position: float):
        self.line_index = line_index
        self.line_position = line_position
        super().__init__(
            "Could not measure line point "
            f"{line_index} at {line_position:.3f} m: maximum displacement reached."
        )


def run_measurements(robot_ip: str, rtde_receive, config: dict, state_path: str | Path) -> None:
    """Measure every valid position along the configured line.

    ``height_mode`` tracks whether the robot is on the safe high plane or the
    low measurement plane. The state file is updated before each position and
    again after its force measurement so another process can follow progress.
    """

    # Reject an obstacle without a safe vertical movement before any robot
    # command is allowed to start.
    high_low_movement(config)
    assert_robot_running(robot_ip)
    try:
        _run_measurements(robot_ip, rtde_receive, config, state_path)
    except BaseException:
        # Includes Ctrl+C and robot safety exceptions. Do not attempt recovery
        # motion here: stop in place and let the operator inspect the robot.
        try:
            stop_robot(robot_ip)
        except Exception as stop_error:
            print(f"Warning: robot stop command failed: {stop_error}", file=sys.stderr)
        raise


def _run_measurements(robot_ip: str, rtde_receive, config: dict, state_path: str | Path) -> None:
    """Implementation separated so the public entry point owns cleanup."""

    height_mode = "high"
    positions = line_positions(config)
    measurement = config["measurement"]
    step = 0

    while step < len(positions):
        # Describe the current line point before moving or measuring.
        index, position = positions[step]
        in_obstacle = is_obstacle(position, config)
        state = {
            "mode": "measurements",
            "line_index": index,
            "line_position": position,
            "height_mode": height_mode,
            "in_obstacle": in_obstacle,
            "last_measurement_success": None,
        }
        write_state(state_path, state)

        print(f"\nLine index {index}, position {position:.3f} m")

        # Never measure inside an obstacle: rise if needed, then jump directly
        # to the next valid measurement point while staying high.
        if in_obstacle:
            if height_mode == "low":
                print("Obstacle: move low -> high")
                low_to_high(robot_ip, rtde_receive, config)
                height_mode = "high"

            next_step = next_measurement_step(positions, step + 1, config)
            if next_step is None:
                print("Obstacle until end of line")
                break

            next_position = positions[next_step][1]
            print(f"Obstacle: jump to next measurement position {next_position:.3f} m")
            translate_along_line(robot_ip, rtde_receive, config, next_position - position)
            step = next_step
            continue

        # At a valid point, descend to measurement height and run the force URP.
        if height_mode == "high":
            print("Measurement point: move high -> low")
            high_to_low(robot_ip, rtde_receive, config)
            height_mode = "low"

        state["height_mode"] = height_mode
        measurement_success = apply_force(
            robot_ip,
            measurement["program_path"],
            measurement["max_displacement"],
            measurement["contact_threshold"],
            measurement["holding_force"],
            measurement["simulation"],
        )
        state["last_measurement_success"] = measurement_success
        write_state(state_path, state)

        if not measurement_success:
            message = (
                f"Could not measure line point {index} at {position:.3f} m: "
                "maximum displacement reached. Returning to p_start_h."
            )
            print(f"\n{message}")

            # The force URP returns to its initial (low) measurement pose.
            # Rise to the safe plane, then undo all line translation so the TCP
            # finishes at p_start_h. Do not continue with the end routine.
            low_to_high(robot_ip, rtde_receive, config)
            height_mode = "high"
            if abs(position) > 1e-12:
                translate_along_line(robot_ip, rtde_receive, config, -position)

            write_state(
                state_path,
                {
                    "mode": "measurement_failed",
                    "line_index": index,
                    "line_position": position,
                    "height_mode": height_mode,
                    "in_obstacle": False,
                    "last_measurement_success": False,
                    "message": message,
                },
            )
            raise MeasurementUnavailableError(index, position)

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
                    low_to_high(robot_ip, rtde_receive, config)
                    height_mode = "high"

                print(f"Pass obstacle at safe height: translate to {next_position:.3f} m")
                translate_along_line(robot_ip, rtde_receive, config, next_position - position)
                step = next_step
                continue

            print("Translate to next line position")
            translate_along_line(robot_ip, rtde_receive, config, next_position - position)

        step += 1

    # Always finish at the safe high level, including after the last measure.
    if height_mode == "low":
        print("\nEnd of line: move low -> high")
        low_to_high(robot_ip, rtde_receive, config)
        height_mode = "high"

    # Publish a final state so the caller knows traversal has finished.
    write_state(
        state_path,
        {
            "mode": "measurements_done",
            "line_index": positions[-1][0],
            "line_position": positions[-1][1],
            "height_mode": height_mode,
            "in_obstacle": False,
            "last_measurement_success": None,
        },
    )
