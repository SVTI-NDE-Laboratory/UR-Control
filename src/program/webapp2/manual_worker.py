"""Isolated manual actions. Terminating this process prevents subsequent commands."""

import json
import sys
import time
from pathlib import Path

from .settings import ROBOT_IP, ROUTINE_FILE, JOINT_TOLERANCE, POSITION_TOLERANCE, ROTATION_TOLERANCE, MANUAL_MOVE_TIMEOUT
from .feedback import Feedback, classify_position
from .waypoint_routes import waypoint_warning, waypoint_motion_options
from .control import read_json
from webapp.launcher import write_json_atomic
from robot_connection import assert_robot_running, assert_robot_safe, get_rtde_receive, stop_robot
from robot_move import movej, movel_pose, tcp_target_errors, wait_until_tcp_stops
from read_routines import read_routines_file, get_waypoint
from run_routine import run_routine
from run_single_routine import assert_at_routine_first_waypoint


def check_waypoint_move(request, receiver, data, directory):
    """Warn from live position, wait without moving, then verify it is unchanged."""
    assert_robot_safe(receiver)
    wait_until_tcp_stops(receiver, timeout=3.0, settle_time=.2)
    pose, joints = receiver.getActualTCPPose(), receiver.getActualQ()
    source = classify_position(pose, joints, data)["waypoint"]
    warning = waypoint_warning(data, source, request["waypoint"], request["motion"])
    if warning is None:
        return True
    decision_file = directory / "waypoint_confirmation.json"
    decision_file.unlink(missing_ok=True)
    write_json_atomic(directory / "state.json", {
        "mode": "waiting_for_waypoint_confirmation", "message": warning,
        "source": source, "target": request["waypoint"], "motion": request["motion"],
    })
    deadline = time.monotonic() + 120
    while not decision_file.exists():
        assert_robot_safe(receiver)
        if time.monotonic() >= deadline:
            raise TimeoutError("Waypoint confirmation timed out. No waypoint move was started.")
        time.sleep(.05)
    decision = read_json(decision_file)
    decision_file.unlink()
    if decision.get("proceed") is not True:
        return False
    assert_robot_safe(receiver)
    wait_until_tcp_stops(receiver, timeout=3.0, settle_time=.2)
    distance, rotation = tcp_target_errors(receiver.getActualTCPPose(), pose)
    actual_joints = receiver.getActualQ()
    if (distance > POSITION_TOLERANCE or rotation > ROTATION_TOLERANCE
            or len(actual_joints) != 6 or len(joints) != 6
            or max(abs(a - b) for a, b in zip(actual_joints, joints)) > JOINT_TOLERANCE):
        raise ValueError("Robot position changed while awaiting confirmation. Select the waypoint again.")
    return True


def run(request, directory):
    """Execute one validated request with fresh safety/position checks and cleanup."""
    state_file = directory / "state.json"
    data = read_routines_file(ROUTINE_FILE)
    feedback = Feedback(directory / "feedback.json", data)
    feedback.start()
    receiver = None
    action = request["action"]
    try:
        write_json_atomic(state_file, {"mode": "connecting", "action": action})
        assert_robot_running(ROBOT_IP)
        receiver = get_rtde_receive(ROBOT_IP)
        assert_robot_safe(receiver)
        feedback.attach(receiver)
        feedback.sample()
        write_json_atomic(state_file, {"mode": "manual", "action": action})
        if action == "waypoint":
            waypoint = get_waypoint(data, request["waypoint"])
            allowed = waypoint_motion_options(request["waypoint"], waypoint)
            if request["motion"] not in {"l", "j"} or not allowed["linear" if request["motion"] == "l" else "joint"]:
                raise ValueError("This waypoint does not allow the selected motion type.")
            if not check_waypoint_move(request, receiver, data, directory):
                write_json_atomic(state_file, {"mode": "idle", "message": "Waypoint move cancelled. No move was started."})
                return
            write_json_atomic(state_file, {"mode": "manual", "action": action})
            if request["motion"] == "l":
                movel_pose(ROBOT_IP, receiver, waypoint["p"], request["acceleration"] / 1000, request["speed"] / 1000, MANUAL_MOVE_TIMEOUT)
            else:
                movej(ROBOT_IP, receiver, waypoint["q"], request["acceleration"], request["speed"], JOINT_TOLERANCE, MANUAL_MOVE_TIMEOUT)
        elif action == "routine":
            assert_at_routine_first_waypoint(receiver, data, request["routine"], JOINT_TOLERANCE)
            run_routine(request["routine"], data, ROBOT_IP, receiver, JOINT_TOLERANCE, MANUAL_MOVE_TIMEOUT, False, True)
        else:
            raise ValueError("Unknown manual action.")
        feedback.sample()
        write_json_atomic(state_file, {"mode": "idle", "message": "Manual action completed."})
    except BaseException as error:
        # Existing motion helpers also stop on errors; cover setup failures here.
        if receiver is not None:
            try:
                stop_robot(ROBOT_IP)
            except Exception as stop_error:
                error = RuntimeError(f"{error}; robot stop failed: {stop_error}")
        write_json_atomic(state_file, {"mode": "error", "message": str(error)})
        raise
    finally:
        feedback.close()
        if receiver is not None:
            receiver.disconnect()


if __name__ == "__main__":
    request_path = Path(sys.argv[1])
    run(json.loads(request_path.read_text()), request_path.parent)
