"""Simulated data acquisition server.

The server waits for JSON messages from the robot control program.
When it receives `{"message": "acquire_data"}`, it waits 1-3 seconds and
responds with `{"message": "data_acquired"}`. It also responds to handshake
and heartbeat messages used by the main program to verify the communication
endpoint.
"""

import argparse
import json
import os
import random
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent
PROGRAM_DIR = PROJECT_ROOT / "src" / "program"
if str(PROGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAM_DIR))

from data_acquisition.timestamped_logging import install_timestamped_tee

CONFIG_SERVER_FILE = SERVER_DIR / "config_server.json"


def process_is_running(process_id: int) -> bool:
    """Return whether a process exists without signalling or modifying it."""

    if os.name == "nt":
        import ctypes

        synchronize = 0x00100000
        wait_timeout = 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, process_id)
        if not handle:
            return False
        try:
            return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == wait_timeout
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def exit_when_parent_stops(parent_process_id: int) -> None:
    """Prevent an orphan server if the web worker forcibly stops main."""

    while process_is_running(parent_process_id):
        time.sleep(0.5)
    os._exit(0)


def read_json_line(connection) -> dict:
    """Read one newline-terminated JSON message.

    The control program sends exactly one request per TCP connection.
    """

    data = b""
    while not data.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            break
        data += chunk

    if not data:
        return {}

    return json.loads(data.decode("utf-8"))


def send_json_line(connection, message: dict) -> None:
    """Send one newline-terminated JSON response.

    Newline framing keeps the protocol simple and easy to debug.
    """

    connection.sendall((json.dumps(message) + "\n").encode("utf-8"))


def handle_request(
    request: dict,
    minimum_acquisition_delay: float,
    maximum_acquisition_delay: float,
) -> dict:
    """Handle one acquisition request.

    A handshake proves that the expected service owns the listening port. Data
    acquisition is currently simulated by a random 1-3 second delay.
    """

    if request.get("message") == "handshake":
        return {
            "message": "handshake_ack",
            "server": "data_acquisition_server",
            "protocol_version": 1,
        }

    if request.get("message") == "heartbeat":
        return {
            "message": "heartbeat_ack",
            "server": "data_acquisition_server",
            "protocol_version": 1,
            "heartbeat_id": request.get("heartbeat_id"),
            "received_at": datetime.now()
            .astimezone()
            .isoformat(timespec="milliseconds"),
        }

    if request.get("message") != "acquire_data":
        return {"message": "error", "error": "unknown message", "request": request}

    acquisition_time = random.uniform(
        minimum_acquisition_delay,
        maximum_acquisition_delay,
    )
    print(f"Acquire data request: {request}")
    time.sleep(acquisition_time)

    return {
        "message": "data_acquired",
        "acquisition_time": acquisition_time,
        "completed_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "request_id": request.get("request_id"),
    }


def run_server(
    host: str,
    port: int,
    minimum_acquisition_delay: float,
    maximum_acquisition_delay: float,
) -> None:
    """Run the simulated acquisition server forever.

    Stop it with Ctrl+C when the test session is finished.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()

        print(f"Data acquisition server listening on {host}:{port}")

        while True:
            connection, address = server.accept()
            threading.Thread(
                target=serve_connection,
                args=(
                    connection,
                    address,
                    minimum_acquisition_delay,
                    maximum_acquisition_delay,
                ),
                daemon=True,
            ).start()


def serve_connection(
    connection,
    address,
    minimum_acquisition_delay: float,
    maximum_acquisition_delay: float,
) -> None:
    """Serve one JSON-line request on one TCP connection."""

    with connection:
        print(f"Connection from {address}")
        request = read_json_line(connection)
        if not request:
            return
        response = handle_request(
            request,
            minimum_acquisition_delay,
            maximum_acquisition_delay,
        )
        send_json_line(connection, response)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--parent-pid", type=int)
    parser.add_argument("--log-file", type=Path)
    arguments = parser.parse_args()
    if arguments.log_file is not None:
        install_timestamped_tee(arguments.log_file)
    if arguments.parent_pid is not None:
        threading.Thread(
            target=exit_when_parent_stops,
            args=(arguments.parent_pid,),
            daemon=True,
            name="parent-process-watchdog",
        ).start()
    config = json.loads(CONFIG_SERVER_FILE.read_text(encoding="utf-8"))
    run_server(
        arguments.host or config["host"],
        arguments.port or config["port"],
        config["minimum_acquisition_delay"],
        config["maximum_acquisition_delay"],
    )
