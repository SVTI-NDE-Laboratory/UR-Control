"""Run the measurement line sequence.

This module assumes the robot starts at `p_start_h` after `run_routine("start")`.
Line motion is always in the tool frame.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from line_planner import is_obstacle, line_positions, next_measurement_step, normalize, scale
from measurement_state import write_state
from robot_move import translate_tool
from simulate_measurement import simulate_measurement


def high_to_low(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the safe high plane to the low measurement plane.

    The motion uses obstacle.direction_high_low in the tool frame.
    """

    obstacle = config["obstacle"]
    measurement = config["measurement"]
    direction = normalize(obstacle["direction_high_low"])
    offset = scale(direction, obstacle["high_low_distance"])
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)


def low_to_high(robot_ip: str, rtde_receive, config: dict) -> None:
    """Move from the low measurement plane back to the safe high plane.

    This uses the inverse of obstacle.direction_high_low in the tool frame.
    """

    obstacle = config["obstacle"]
    measurement = config["measurement"]
    direction = normalize(obstacle["direction_high_low"])
    offset = scale(direction, -obstacle["high_low_distance"])
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)


def translate_along_line(robot_ip: str, rtde_receive, config: dict, distance: float) -> None:
    """Move a distance along the configured tool-frame line direction.

    The direction_start_end vector is normalized, then scaled by the requested distance.
    """

    line = config["line"]
    measurement = config["measurement"]
    direction = normalize(line["direction_start_end"])
    offset = scale(direction, distance)
    translate_tool(robot_ip, rtde_receive, offset, measurement["acceleration"], measurement["speed"], 30.0)


def perform_measurement(robot_ip: str, rtde_receive, config: dict) -> bool:
    """Perform the current temporary measurement action.

    For now this calls simulate_measurement instead of launching a URP.
    """

    return simulate_measurement(robot_ip, rtde_receive, config)


def run_measurements(robot_ip: str, rtde_receive, config: dict, state_path: str | Path) -> None:
    """Run the full measurement line traversal.

    The robot starts high, drops low for valid measurement points, and stays high through obstacles.
    """

    height_mode = "high"
    positions = line_positions(config)
    step = 0

    while step < len(positions):
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
        else:
            if height_mode == "high":
                print("Measurement point: move high -> low")
                high_to_low(robot_ip, rtde_receive, config)
                height_mode = "low"

            state["height_mode"] = height_mode
            state["last_measurement_success"] = perform_measurement(robot_ip, rtde_receive, config)
            write_state(state_path, state)

        if step < len(positions) - 1:
            next_position = positions[step + 1][1]
            next_in_obstacle = is_obstacle(next_position, config)

            if next_in_obstacle:
                if height_mode == "low":
                    print("Next point is obstacle: move low -> high before jumping obstacle")
                    low_to_high(robot_ip, rtde_receive, config)
                    height_mode = "high"

                next_step = next_measurement_step(positions, step + 2, config)
                if next_step is None:
                    print("Obstacle until end of line")
                    break

                jump_position = positions[next_step][1]
                print(f"Jump obstacle: translate to {jump_position:.3f} m")
                translate_along_line(robot_ip, rtde_receive, config, jump_position - position)
                step = next_step
                continue

            print("Translate to next line position")
            translate_along_line(robot_ip, rtde_receive, config, next_position - position)

        step += 1

    if height_mode == "low":
        print("\nEnd of line: move low -> high")
        low_to_high(robot_ip, rtde_receive, config)
        height_mode = "high"

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
