"""Own the single robot worker process shared by web API requests."""

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

if __package__:
    from .launcher import start_program, write_json_atomic
    from .settings import ROBOT_IP
else:
    from launcher import start_program, write_json_atomic
    from settings import ROBOT_IP

from robot_connection import stop_robot


class WorkerBusyError(RuntimeError):
    """Raised when a robot action is requested while another one is active."""


class WorkerManager:
    """Synchronize measurement worker lifecycle operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._kind: str | None = None
        self._state_file: Path | None = None

    def _assert_available(self) -> None:
        if self._process is not None and self._process.poll() is None:
            raise WorkerBusyError(
                f"A {self._kind or 'robot'} worker is already running."
            )

    def start_measurement(
        self,
        config: dict[str, Any],
        output_directory: Path,
        show_terminal: bool,
        routine_file: Path,
    ) -> dict[str, Any]:
        with self._lock:
            self._assert_available()
            self._process = start_program(
                config, output_directory, show_terminal, routine_file
            )
            self._kind = "measurement"
            self._state_file = output_directory / "state.json"
            return self.snapshot_locked()

    def stop(self, reason: str) -> dict[str, Any]:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                self._process = None
                raise RuntimeError("No robot worker is currently running.")

            stop_error: Exception | None = None
            try:
                stop_robot(ROBOT_IP)
            except Exception as error:
                stop_error = error

            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

            if self._state_file is not None:
                try:
                    state = json.loads(self._state_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    state = {}
                state.update({"mode": "stopped", "reason": reason})
                if stop_error is not None:
                    state.update(
                        {
                            "mode": "error",
                            "message": (
                                f"Worker stopped, but robot stop failed: {stop_error}"
                            ),
                        }
                    )
                write_json_atomic(self._state_file, state)

            self._process = None
            result = self.snapshot_locked()
            if stop_error is not None:
                raise RuntimeError(
                    f"Worker stopped, but the robot stop command failed: {stop_error}"
                )
            return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self.snapshot_locked()

    def snapshot_locked(self) -> dict[str, Any]:
        process = self._process
        running = process is not None and process.poll() is None
        return_code = None if process is None or running else process.returncode
        return {
            "running": running,
            "kind": self._kind,
            "return_code": return_code,
            "state_file": str(self._state_file) if self._state_file else None,
        }
