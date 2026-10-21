"""Flexible session using the existing CLI's plane, entry, exit and force helpers.

The session owns the shared worker slot until End or Stop. Robot feedback is
connected for each action and disconnected while waiting for a browser command.
"""

import math
import sys
import time
from pathlib import Path
from uuid import uuid4

from .settings import ROBOT_IP, ROUTINE_FILE, POSITION_TOLERANCE, ROTATION_TOLERANCE, PROFILE
from .profile import read_object
from .feedback import Feedback, classify_position
from .control import read_json
from webapp.launcher import write_json_atomic
from src.program.commands import run_flexible_measurement as flexible
from robot_connection import assert_at_home, assert_robot_running, assert_robot_safe, get_rtde_receive, stop_robot
from robot_move import tcp_target_errors, wait_until_tcp_stops
from read_routines import read_routines_file

flexible.ROBOT_IP = ROBOT_IP


def plane_geometry(data):
    """Resolve the exact same measurement frame as the flexible CLI."""
    return flexible.line_geometry(flexible.MEASUREMENT_CONFIG, data)


def validate_target(x, y, geometry, outside_range_confirmed=False):
    """Require explicit confirmation before extending the configured XY range."""
    if not all(math.isfinite(value) for value in (x, y)):
        raise ValueError("X and Y must be finite numbers.")
    if not outside_range_confirmed:
        flexible.validate_manual_y(y)
        if not 0 <= x <= geometry["taught_length"]:
            raise ValueError(f"X must be between 0 and {geometry['taught_length']:.3f} mm, or confirm the out-of-range movement.")


def classify_plane(pose, joints, data):
    """Report actual measurement-frame XY and verify the bounded low plane."""
    result = classify_position(pose, joints, data)
    geometry = plane_geometry(data)
    x, y = flexible.pose_to_measurement_xy(pose, data, geometry)
    target = flexible.measurement_pose(data, geometry, x, y, allow_x_outside_taught_range=True)
    distance, rotation = tcp_target_errors(pose, target)
    tolerance_mm = POSITION_TOLERANCE * 1000
    result["in_measurement_plane"] = distance <= POSITION_TOLERANCE and rotation <= ROTATION_TOLERANCE
    result["measurement_zone"] = (result["in_measurement_plane"]
        and -tolerance_mm <= x <= geometry["taught_length"] + tolerance_mm
        and flexible.MIN_MANUAL_Y - tolerance_mm <= y <= flexible.MAX_MANUAL_Y + tolerance_mm)
    result["measurement_xy"] = {"X": x, "Y": y}
    return result


def assert_in_plane(receiver, data, allow_outside_range=False):
    """Recheck safety, actual plane/orientation, and stationary TCP before action."""
    assert_robot_safe(receiver)
    wait_until_tcp_stops(receiver, timeout=3.0, settle_time=.2)
    result = classify_plane(receiver.getActualTCPPose(), receiver.getActualQ(), data)
    if not result["in_measurement_plane"]:
        raise ValueError("Robot position or tool orientation is outside the taught measurement plane.")
    if not allow_outside_range and not result["measurement_zone"]:
        raise ValueError("Robot must be within the configured measurement range for this action.")
    return result


def perform_action(action, receiver, data, geometry, state_file):
    """Execute one session step. Exceptions terminate the session and stop motion."""
    acceleration = flexible.LINEAR_ACCELERATION / 1000
    speed = flexible.LINEAR_SPEED / 1000
    name = action["action"]
    if name == "start":
        assert_at_home(receiver, data["waypoints"]["Home"]["q"], flexible.HOME_JOINT_TOLERANCE)
        flexible.run_entry_sequence(receiver, data, geometry, acceleration, speed)
        assert_in_plane(receiver, data)
        return
    position = assert_in_plane(receiver, data, allow_outside_range=name in {"move", "end"})
    if name == "move":
        confirmed = action.get("outside_range_confirmed", False) is True
        validate_target(action["x"], action["y"], geometry, confirmed)
        target = flexible.measurement_pose(data, geometry, action["x"], action["y"], allow_x_outside_taught_range=confirmed)
        flexible.movel_pose(ROBOT_IP, receiver, target, acceleration, speed, flexible.WAIT_TIMEOUT)
        assert_in_plane(receiver, data, allow_outside_range=True)
    elif name == "force":
        if (not all(math.isfinite(action[key]) for key in ("threshold", "force", "duration"))
                or action["threshold"] <= 0 or action["force"] < action["threshold"] or not 0 <= action["duration"] <= 8):
            raise ValueError("Use positive forces, contact force at least the threshold, and a hold from 0 to 8 seconds.")
        # Reuse force parameter validation and the controller-side return cycle.
        measurement, _ = flexible.force_measurement_settings([str(action["threshold"]), str(action["force"]), str(action["duration"])])
        measurement["max_displacement"] = read_object(PROFILE.paths["measurement_defaults"])["measurement"]["max_displacement"]
        if not math.isfinite(measurement["max_displacement"]) or measurement["max_displacement"] <= 0:
            raise ValueError("Maximum displacement must be positive and finite.")

        def hold(context):
            write_json_atomic(state_file, {"mode": "force_hold"})
            started = time.monotonic()
            while time.monotonic() - started < action["duration"]:
                assert_robot_safe(receiver)
                time.sleep(min(.05, max(0, action["duration"] - (time.monotonic() - started))))
            write_json_atomic(state_file, {"mode": "force_return"})
            return {"acquisition_time": time.monotonic() - started}

        success, _ = flexible.apply_force(ROBOT_IP, measurement["program_path"], measurement["max_displacement"],
            measurement["contact_threshold"], measurement["holding_force"], action.get("simulation", False),
            acquire_data=hold if measurement["stop_method"] == "client_feedback" else None,
            stop_method=measurement["stop_method"],
            hold_duration=measurement["hold_duration"],
            on_force_success=lambda timestamp: write_json_atomic(state_file, {"mode": "force_hold"}),
            acquisition_context={"measurement_index": "manual", "x_coordinate": position["measurement_xy"]["X"],
                                 "y_coordinate": position["measurement_xy"]["Y"], "acquisition_label": "local force hold"})
        assert_in_plane(receiver, data)
        if not success:
            return {"force_reached": False, "action_error": "Contact threshold was not reached before the approach limit. The robot has returned to the measurement plane. You can adjust the settings or position and try again."}
        return {"force_reached": True}
    elif name == "end":
        flexible.run_exit_sequence(receiver, data, geometry, acceleration, speed)
        assert_at_home(receiver, data["waypoints"]["Home"]["q"], flexible.HOME_JOINT_TOLERANCE)
    else:
        raise ValueError("Unknown flexible measurement action.")


def run(directory):
    """Enter at p_start_l, wait disconnected, then execute serialized commands."""
    flexible.ENTRY_SIDE = "start"
    data = read_routines_file(ROUTINE_FILE)
    geometry = plane_geometry(data)
    state_file = directory / "state.json"
    command_file = directory / "command.json"
    feedback = Feedback(directory / "feedback.json", data, classifier=classify_plane)
    feedback.start()
    receiver = None
    action = {"action": "start"}
    try:
        while True:
            name = action["action"]
            write_json_atomic(state_file, {"mode": "entry_routine" if name == "start" else "exit_routine" if name == "end" else name})
            try:
                assert_robot_running(ROBOT_IP)
                receiver = get_rtde_receive(ROBOT_IP)
                feedback.attach(receiver)
                if name == "force":
                    with feedback.force_cycle():
                        result = perform_action(action, receiver, data, geometry, state_file)
                else:
                    result = perform_action(action, receiver, data, geometry, state_file)
                feedback.sample()
            finally:
                feedback.detach()
                if receiver is not None:
                    receiver.disconnect()
                    receiver = None
                feedback.sample()
            if name == "end":
                write_json_atomic(state_file, {"mode": "idle"})
                return
            ready = {"mode": "waiting_for_command", **(result or {})}
            if ready.get("action_error"):
                ready["notification_id"] = uuid4().hex
            write_json_atomic(state_file, ready)
            while not command_file.exists():
                time.sleep(.05)
            action = read_json(command_file)
            # Publish busy before consuming the file, so two requests cannot queue.
            write_json_atomic(state_file, {"mode": "command_pending", "action": action["action"]})
            command_file.unlink()
    except BaseException as error:
        try:
            stop_robot(ROBOT_IP)
        except Exception as stop_error:
            error = RuntimeError(f"{error}; robot stop failed: {stop_error}")
        write_json_atomic(state_file, {"mode": "error", "message": str(error)})
        raise
    finally:
        feedback.close()


if __name__ == "__main__":
    run(Path(sys.argv[1]))
