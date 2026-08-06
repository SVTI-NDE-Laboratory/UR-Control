"""Temporary measurement simulation."""

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from data_acquisition_client import request_data_acquisition
from force_approach_urp import launch_force_approach_urp
from robot_move import movel_pose


def current_tcp_pose(rtde_receive) -> list[float]:
    """Return the current TCP pose from RTDE.

    The pose is sent to the acquisition server as context for the data record.
    """

    return list(rtde_receive.getActualTCPPose())


def current_tcp_force(rtde_receive) -> list[float]:
    """Return the current TCP force if available.

    Some RTDE versions expose force; if not, the field is sent as an empty list.
    """

    if not hasattr(rtde_receive, "getActualTCPForce"):
        return []
    return list(rtde_receive.getActualTCPForce())


def acquire_data(rtde_receive, config: dict) -> dict:
    """Send an acquire_data message and wait for data_acquired.

    This simulates the future synchronization with a real acquisition device.
    """

    data_acquisition = config["data_acquisition"]
    payload = {
        "message": "acquire_data",
        "request_id": f"measurement_{int(time.time() * 1000)}",
        "tcp_pose": current_tcp_pose(rtde_receive),
        "tcp_force": current_tcp_force(rtde_receive),
    }

    return request_data_acquisition(
        data_acquisition["host"],
        data_acquisition["port"],
        payload,
        data_acquisition["timeout"],
    )


def simulate_measurement(robot_ip: str, rtde_receive, config: dict) -> bool:
    """Perform a force approach, acquire data on success, then return low.

    The saved low pose is restored after success or failure.
    """

    measurement = config["measurement"]
    low_pose = current_tcp_pose(rtde_receive)
    success = False

    try:
        print(f"Saved low pose before force approach: {low_pose}")
        print(f"Force approach URP: {config['force_approach_urp']['program_name']}")
        success = launch_force_approach_urp(robot_ip, config)

        if success:
            response = acquire_data(rtde_receive, config)
            print(f"Data acquisition: {response['message']}")
        else:
            print("Force approach failed: max displacement reached")

        return success

    finally:
        print("Returning linearly to saved low pose")
        movel_pose(robot_ip, rtde_receive, low_pose, measurement["acceleration"], measurement["speed"], 30.0)
