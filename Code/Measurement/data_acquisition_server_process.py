"""Start and stop the simulated data acquisition server process."""

import socket
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPT = PROJECT_ROOT / "Data Acquisition Server" / "data_acquisition_server.py"


def wait_for_server(host: str, port: int, timeout: float) -> None:
    """Wait until the acquisition server accepts TCP connections.

    This prevents the main program from requesting data before the server is ready.
    """

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)

    raise TimeoutError(f"Data acquisition server did not start on {host}:{port}.")


def start_data_acquisition_server(config: dict) -> subprocess.Popen:
    """Start the simulated acquisition server as a child process.

    The server is stopped later by stop_data_acquisition_server.
    """

    data_acquisition = config["data_acquisition"]
    process = subprocess.Popen([sys.executable, str(SERVER_SCRIPT)])
    wait_for_server(data_acquisition["host"], data_acquisition["port"], 5.0)
    return process


def stop_data_acquisition_server(process: subprocess.Popen | None) -> None:
    """Stop the simulated acquisition server process.

    This is safe to call with None and is intended for use in a finally block.
    """

    if process is None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
