"""Run a force approach from Python-controlled motion steps."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from measurement_config import read_measurement_config
from line_planner import normalize
from robot_move import translate_tool
from robot_connection import assert_remote_control, get_rtde_receive


ROBOT_IP = "192.168.3.10"
MEASUREMENT_CONFIG_FILE = PROJECT_ROOT / "Configuration" / "measurement_config.json"


def force_step_offset(config: dict) -> list[float]:
    """Return one probing step in the configured tool-frame direction.

    Python sends one small bounded motion, then checks RTDE force before the next step.
    """

    measurement = config["measurement"]
    obstacle = config["obstacle"]
    step_distance = measurement.get("force_step_distance", min(0.001, measurement["max_displacement"]))
    if step_distance <= 0:
        raise ValueError("measurement.force_step_distance must be positive.")

    direction = normalize(measurement.get("force_direction", obstacle["direction_high_low"]))
    return [
        direction[0] * step_distance,
        direction[1] * step_distance,
        direction[2] * step_distance,
    ]


def position_distance(start_pose: list[float], current_pose: list[float]) -> float:
    """Return Cartesian distance between two TCP poses.

    Only XYZ is used because max_displacement limits probing travel.
    """

    dx = current_pose[0] - start_pose[0]
    dy = current_pose[1] - start_pose[1]
    dz = current_pose[2] - start_pose[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def tcp_force_norm(rtde_receive) -> float:
    """Return the norm of the measured TCP force vector.

    The first three RTDE force components are Fx, Fy, and Fz.
    """

    force = rtde_receive.getActualTCPForce()
    fx, fy, fz = force[:3]
    return (fx * fx + fy * fy + fz * fz) ** 0.5


def launch_force_approach(robot_ip: str, rtde_receive, config: dict) -> bool:
    """Send force approach to the robot and return success/failure.

    Python sends one small motion step at a time and checks RTDE force between steps.
    """

    measurement = config["measurement"]
    target_force = measurement.get("force_reached_limit", measurement["target_force"])
    max_displacement = measurement["max_displacement"]
    acceleration = measurement["acceleration"]
    speed = measurement["speed"]

    start_pose = list(rtde_receive.getActualTCPPose())
    moved_distance = 0.0

    while moved_distance < max_displacement:
        if tcp_force_norm(rtde_receive) >= target_force:
            return True

        remaining_distance = max_displacement - moved_distance
        offset = force_step_offset(config)
        step_norm = position_distance([0, 0, 0, 0, 0, 0], [offset[0], offset[1], offset[2], 0, 0, 0])

        if step_norm > remaining_distance:
            scale = remaining_distance / step_norm
            offset = [offset[0] * scale, offset[1] * scale, offset[2] * scale]
            step_norm = remaining_distance

        translate_tool(robot_ip, rtde_receive, offset, acceleration, speed, 5.0)
        moved_distance = position_distance(start_pose, rtde_receive.getActualTCPPose())

    return tcp_force_norm(rtde_receive) >= target_force


if __name__ == "__main__":
    measurement_config = read_measurement_config(MEASUREMENT_CONFIG_FILE, verbose=True)

    input("Press Enter to launch force approach, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)
    rtde_receive = get_rtde_receive(ROBOT_IP)

    success = launch_force_approach(ROBOT_IP, rtde_receive, measurement_config)
    print(f"force_approach_success={success}")

    rtde_receive.disconnect()
