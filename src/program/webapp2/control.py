"""One process owner for manual actions and the existing automatic workflow."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from uuid import uuid4

from .settings import ROOT, RUNTIME, ROUTINE_FILE
from webapp.worker_manager import WorkerManager
from webapp.launcher import write_json_atomic


def read_json(path, fallback=None):
    """Read atomically published worker output; tolerate startup/missing files."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {} if fallback is None else fallback


class ControlWorkers(WorkerManager):
    """Keep the original stop/snapshot API while adding isolated manual workers."""

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self.directory = None

    def _spawn(self, module, arguments, terminal=False):
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe":
            executable = executable.with_name("python.exe")
        flags = (subprocess.CREATE_NEW_CONSOLE if terminal else subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
        log = (self.directory / "worker.log").open("w", encoding="utf-8")
        try:
            self._process = subprocess.Popen([str(executable), "-u", "-m", module, *map(str, arguments)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=None if terminal else log,
                stderr=None if terminal else subprocess.STDOUT, creationflags=flags)
        except OSError as error:
            self._process = None
            write_json_atomic(self._state_file, {"mode": "error", "message": f"Could not start worker: {error}"})
            raise
        finally:
            log.close()

    def start_manual(self, request):
        with self._lock:
            self._assert_available()
            self.directory = RUNTIME / uuid4().hex
            self.directory.mkdir(parents=True)
            self._state_file = self.directory / "state.json"
            self._kind = "manual"
            write_json_atomic(self._state_file, {"mode": "starting", "action": request["action"]})
            request_path = self.directory / "request.json"
            write_json_atomic(request_path, request)
            self._spawn("src.program.webapp2.manual_worker", [request_path])
            return self.snapshot_locked()

    def start_measurement(self, config, output_directory, show_terminal, routine_file):
        with self._lock:
            self._assert_available()
            if routine_file.resolve() != ROUTINE_FILE.resolve():
                raise ValueError("WebApp 2.0 uses the fixed installation routine file.")
            self.directory = output_directory
            self._state_file = output_directory / "state.json"
            self._kind = "measurement"
            config_path = output_directory / "config_used.json"
            write_json_atomic(config_path, config)
            write_json_atomic(self._state_file, {"mode": "starting"})
            (output_directory / "feedback.json").unlink(missing_ok=True)
            signal = output_directory / "start_movement.signal"
            signal.unlink(missing_ok=True)
            self._spawn("src.program.webapp2.measurement_worker", ["--config", config_path,
                "--operator-confirmed", "--start-signal-file", signal, "--routines-file", ROUTINE_FILE,
                "--output-dir", output_directory], show_terminal)
            return self.snapshot_locked()

    def start_flexible(self):
        """Reserve the robot for a flexible session, including between actions."""
        with self._lock:
            self._assert_available()
            self.directory = RUNTIME / uuid4().hex
            self.directory.mkdir(parents=True)
            self._state_file = self.directory / "state.json"
            self._kind = "flexible"
            write_json_atomic(self._state_file, {"mode": "starting"})
            self._spawn("src.program.webapp2.flexible_worker", [self.directory])
            return self.snapshot_locked()

    def send_flexible(self, request):
        """Queue exactly one command only when the session is waiting."""
        with self._lock:
            worker = self.snapshot_locked()
            if not worker["running"] or worker["kind"] != "flexible":
                raise RuntimeError("Start a flexible measurement session first.")
            state = read_json(self._state_file)
            if state.get("mode") != "waiting_for_command" or (self.directory / "command.json").exists():
                raise RuntimeError("Wait for the current flexible action to finish.")
            write_json_atomic(self._state_file, {"mode": "command_pending", "action": request["action"]})
            try:
                write_json_atomic(self.directory / "command.json", request)
            except OSError:
                write_json_atomic(self._state_file, state)
                raise
            return self.snapshot_locked()

    def confirm_waypoint(self, state_file, proceed):
        """Bind a decision to the worker currently awaiting a waypoint warning."""
        with self._lock:
            worker = self.snapshot_locked()
            if (not worker["running"] or worker["kind"] != "manual"
                    or worker["state_file"] != state_file):
                raise RuntimeError("This waypoint confirmation is no longer active.")
            state = read_json(self._state_file)
            decision = self.directory / "waypoint_confirmation.json"
            if state.get("mode") != "waiting_for_waypoint_confirmation" or decision.exists():
                raise RuntimeError("No waypoint move is waiting for confirmation.")
            write_json_atomic(decision, {"proceed": proceed})
            return worker

    def stop(self, reason):
        """Kill the command producer before issuing the final hardware stop.

        The base implementation stops the robot before process termination. A
        second stop after termination closes the window for a subsequent step.
        Keep an error visible if either stop attempt cannot be confirmed.
        """
        from robot_connection import stop_robot
        from .settings import ROBOT_IP
        with self._lock:
            self._assert_running()
            flexible_session = self._kind == "flexible"
            was_ready = flexible_session and read_json(self._state_file).get("mode") == "waiting_for_command"
            try:
                result = super().stop(reason)
            finally:
                try:
                    stop_robot(ROBOT_IP)
                except RuntimeError as error:
                    write_json_atomic(self._state_file, {"mode": "error", "message": f"Worker terminated but robot stop failed: {error}"})
                    raise
            if flexible_session:
                state = read_json(self._state_file)
                state.update({"mode": "error", "notification_id": uuid4().hex,
                              "message": "Flexible measurement program stopped by the operator"
                              + (" while Ready." if was_ready else ".")
                              + " Start a new session to continue."})
                write_json_atomic(self._state_file, state)
            return result

    def _assert_running(self):
        if not self.snapshot_locked()["running"]:
            raise RuntimeError("No robot worker is currently running.")

    def details(self):
        with self._lock:
            worker = self.snapshot_locked()
            program = read_json(self._state_file) if self._state_file else {}
            feedback = read_json(self.directory / "feedback.json") if self.directory else {}
            if not worker["running"]:
                feedback.update(robot_connected=False, moving=None, force_mode=False, acquisition_connected=False, acquisition_listening=False)
            if worker["return_code"] not in (None, 0) and program.get("mode") not in {"error", "stopped", "unsafe_start", "measurement_failed"}:
                program = {"mode": "error", "message": f"Worker exited with code {worker['return_code']}; see worker.log."}
            return worker, program, feedback
