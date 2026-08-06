"""Launch a force approach URP and wait for its socket result."""

import json
import socket
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import dashboard_command


def wait_for_force_urp_result(host: str, port: int, timeout: float) -> bool:
    """Wait for one JSON result message from the force approach URP.

    Expected message: {"message": "force_approach_done", "success": true/false}.
    """

    with socket.create_server((host, port), reuse_port=False) as server:
        server.settimeout(timeout)
        connection, _address = server.accept()

        with connection:
            data = connection.recv(4096).decode("utf-8", errors="replace").strip()

    result = json.loads(data)
    if result.get("message") != "force_approach_done":
        raise ValueError(f"Unexpected force approach message: {result}")

    return bool(result["success"])


def launch_urp(robot_ip: str, program_name: str) -> None:
    """Load and play one URP program through the Dashboard server.

    The program name must be the path as seen by the robot controller.
    """

    load_response = dashboard_command(robot_ip, f"load {program_name}")
    if not load_response.lower().startswith("loading program"):
        raise RuntimeError(f"Could not load URP '{program_name}': {load_response}")

    play_response = dashboard_command(robot_ip, "play")
    if "starting program" not in play_response.lower():
        raise RuntimeError(f"Could not start URP '{program_name}': {play_response}")


def launch_force_approach_urp(robot_ip: str, config: dict) -> bool:
    """Launch the configured force approach URP and return success/failure.

    Python listens before launching so the URP can immediately send its result.
    """

    force_config = config["force_approach_urp"]
    host = force_config["result_host"]
    port = force_config["result_port"]
    timeout = force_config["timeout"]
    program_name = force_config["program_name"]

    with socket.create_server((host, port), reuse_port=False) as server:
        server.settimeout(timeout)
        launch_urp(robot_ip, program_name)
        connection, _address = server.accept()

        with connection:
            data = connection.recv(4096).decode("utf-8", errors="replace").strip()

    result = json.loads(data)
    if result.get("message") != "force_approach_done":
        raise ValueError(f"Unexpected force approach message: {result}")

    return bool(result["success"])
