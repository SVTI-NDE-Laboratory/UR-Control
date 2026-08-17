"""Start and stop the simulated data acquisition server process."""

import os
import subprocess
import sys
import time
import json
from pathlib import Path

from data_acquisition_client import handshake_data_acquisition_server


SERVER_DIR = Path(__file__).resolve().parent
SERVER_SCRIPT = SERVER_DIR / "data_acquisition_server.py"
CONFIG_FILE = SERVER_DIR / "config.json"


def wait_for_server(
    process: subprocess.Popen, host: str, port: int, timeout: float
) -> dict:
    """Wait for a successful application-level server handshake.

    Opening a TCP port alone is insufficient because another process could own
    it. The handshake verifies the server identity and protocol version.
    """

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        return_code = process.poll()
        if return_code is not None:
            raise RuntimeError(
                f"Data acquisition server exited during startup with code {return_code}."
            )
        try:
            return handshake_data_acquisition_server(host, port, timeout=0.5)
        except (OSError, RuntimeError):
            time.sleep(0.1)

    raise TimeoutError(f"Data acquisition server did not start on {host}:{port}.")


def start_data_acquisition_server(log_path: str | Path) -> tuple[subprocess.Popen, dict]:
    """Start the acquisition server and complete its startup handshake.

    The server is stopped later by stop_data_acquisition_server.
    """

    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    creationflags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            str(SERVER_SCRIPT),
            "--parent-pid",
            str(os.getpid()),
            "--log-file",
            str(Path(log_path).resolve()),
        ],
        cwd=SERVER_DIR,
        creationflags=creationflags,
    )
    try:
        handshake = wait_for_server(
            process,
            config["host"],
            config["port"],
            config["startup_timeout"],
        )
    except BaseException:
        stop_data_acquisition_server(process)
        raise
    return process, {**config, "handshake": handshake}


def stop_data_acquisition_server(process: subprocess.Popen | None) -> None:
    """Stop the simulated acquisition server process.

    This is safe to call with None and is intended for use in a finally block.
    """

    if process is None:
        return

    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
