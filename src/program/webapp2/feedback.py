"""Pose classification and feedback from an action's existing RTDE connection."""

import math
import sys
import threading
from contextlib import contextmanager
from datetime import datetime

from .settings import POSITION_TOLERANCE, ROTATION_TOLERANCE, JOINT_TOLERANCE
from robot_move import tcp_target_errors
from robot_connection import assert_robot_safe
from webapp.launcher import write_json_atomic
from data_acquisition.server_control import AcquisitionControlServer


def classify_position(pose, joints, data):
    """Identify a taught waypoint and the bounded low measurement segment.

    Two points cannot define a plane. Until a second in-plane direction and
    permitted width are taught, only their segment is accepted for manual force.
    Orientation must match the nearer endpoint, including at intermediate points.
    """
    start = data["waypoints"]["p_start_l"]["p"]
    end = data["waypoints"]["p_end_l"]["p"]
    vector = [end[i] - start[i] for i in range(3)]
    length2 = sum(v * v for v in vector)
    if length2 <= 1e-12:
        raise ValueError("Measurement zone endpoints must be distinct.")
    fraction = sum((pose[i] - start[i]) * vector[i] for i in range(3)) / length2
    nearest = [start[i] + max(0, min(1, fraction)) * vector[i] for i in range(3)]
    endpoint = start if fraction <= 0.5 else end
    target = nearest + endpoint[3:]
    distance, rotation = tcp_target_errors(pose, target)
    zone = distance <= POSITION_TOLERANCE and rotation <= ROTATION_TOLERANCE
    name = None
    for candidate, waypoint in data["waypoints"].items():
        if "q" in waypoint:
            match = len(joints) == 6 and max(abs(a - b) for a, b in zip(joints, waypoint["q"])) <= JOINT_TOLERANCE
        else:
            errors = tcp_target_errors(pose, waypoint["p"])
            match = errors[0] <= POSITION_TOLERANCE and errors[1] <= ROTATION_TOLERANCE
        if match:
            name = candidate
            break
    return {"waypoint": name, "measurement_zone": zone,
            "tcp_position": {"X": pose[0] * 1000, "Y": pose[1] * 1000, "Z": pose[2] * 1000},
            "line_position_mm": fraction * math.sqrt(length2) * 1000}


class TrackedServer(AcquisitionControlServer):
    """Report current TCP connections rather than a latched historical ALIVE."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clients = 0
        self.clients_lock = threading.Lock()

    def _serve_client(self, connection, address):
        with self.clients_lock:
            self.clients += 1
        try:
            super()._serve_client(connection, address)
        finally:
            with self.clients_lock:
                self.clients -= 1


class Feedback:
    """Sample only while a worker owns a robot connection; never connect to poll."""

    def __init__(self, path, data, classifier=classify_position):
        self.path, self.data = path, data
        self.classifier = classifier
        self.receiver = None
        self.server = None
        self.force_mode = False
        self.lock = threading.RLock()
        self.finished = threading.Event()
        self.last = {"robot_connected": False, "moving": None, "force_mode": False, "measurement_zone": False}
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def attach(self, receiver):
        with self.lock:
            self.receiver = receiver

    def detach(self):
        with self.lock:
            self.receiver = None

    @contextmanager
    def force_cycle(self):
        """Report force-program activity independently of RTDE connection state."""
        try:
            with self.lock:
                self.force_mode = True
                self.sample()
            yield
        finally:
            with self.lock:
                self.force_mode = False
                self.sample()

    def sample(self):
        with self.lock:
            result = dict(self.last)
            result.update(robot_connected=self.receiver is not None,
                          force_mode=self.force_mode and self.receiver is not None,
                          acquisition_listening=self.server is not None,
                          acquisition_connected=bool(self.server and self.server.clients))
            if self.receiver is not None:
                try:
                    assert_robot_safe(self.receiver)
                    result.update(self.classifier(self.receiver.getActualTCPPose(), self.receiver.getActualQ(), self.data))
                    speed = self.receiver.getActualTCPSpeed()
                    result["moving"] = result["force_mode"] or any(abs(v) > 1e-4 for v in speed)
                    result["observed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                    result.pop("feedback_error", None)
                except Exception as error:
                    result.update(feedback_error=str(error), measurement_zone=False, moving=None, force_mode=False)
            else:
                result["moving"] = None
            self.last = result
            write_json_atomic(self.path, result)

    def _run(self):
        write_failed = False
        while not self.finished.wait(0.2):
            try:
                self.sample()
                write_failed = False
            except OSError as error:
                if not write_failed:
                    print(f"Warning: feedback could not be published; sampling will retry: {error}", file=sys.stderr)
                write_failed = True

    def close(self):
        self.finished.set()
        self.thread.join(timeout=2)
        self.detach()
        self.server = None
        self.sample()
