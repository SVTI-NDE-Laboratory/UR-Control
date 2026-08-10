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

from line_planner import is_obstacle, line_positions, next_measurement_step
from measurement_movement import high_to_low, low_to_high, translate_along_line
from measurement_state import write_state
from apply_force import apply_force


def run_measurements(robot_ip: str, rtde_receive, config: dict, state_path: str | Path) -> None:
    """Measure every valid position along the configured line.

    ``height_mode`` tracks whether the robot is on the safe high plane or the
    low measurement plane. The state file is updated before each position and
    again after its force measurement so another process can follow progress.
    """

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
        state["last_measurement_success"] = apply_force(robot_ip, measurement["program_path"], measurement["max_displacement"], measurement["contact_threshold"], measurement["holding_force"], measurement["simulation"])
        write_state(state_path, state)

        # Move to the following point. If an obstacle begins next, rise and
        # jump over its complete range instead of visiting each blocked point.
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
