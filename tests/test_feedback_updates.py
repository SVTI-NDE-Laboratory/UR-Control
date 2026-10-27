"""Live feedback survives transient Windows file locks and publishes mid-move."""

import json
import sys
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import flexible_worker as worker, measurement_worker
from src.program.webapp2.feedback import Feedback
from src.program.webapp2.settings import ROUTINE_FILE
from webapp import launcher
import atomic_json
from read_routines import read_routines_file


class AtomicPublishingTests(unittest.TestCase):
    def test_temporary_destination_lock_is_retried_without_losing_json(self):
        replace = Path.replace
        attempts = []

        def locked_once(staging, destination):
            attempts.append(staging)
            if len(attempts) == 1:
                raise PermissionError("Reader temporarily holds destination")
            return replace(staging, destination)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "feedback.json"
            target.write_text('{"old": true}')
            with patch.object(Path, "replace", new=locked_once):
                launcher.write_json_atomic(target, {"X": 123, "Y": -50})
            self.assertEqual(json.loads(target.read_text()), {"X": 123, "Y": -50})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_permanent_lock_preserves_previous_json_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "feedback.json"
            target.write_text('{"old": true}')
            with patch.object(Path, "replace", side_effect=PermissionError("Locked")), patch.object(atomic_json.time, "monotonic", side_effect=[0, 1]):
                with self.assertRaises(PermissionError):
                    launcher.write_json_atomic(target, {"new": True})
            self.assertEqual(json.loads(target.read_text()), {"old": True})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_concurrent_writers_do_not_share_staging_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            with ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda index: launcher.write_json_atomic(target, {"index": index, "payload": "x" * 1000}), range(16)))
            self.assertIn(json.loads(target.read_text())["index"], range(16))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


class LiveFeedbackTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop("UR15_WALL_COORDINATES", None)

    def test_automatic_plane_feedback_tracks_motion_and_rejects_high_plane(self):
        data = read_routines_file(ROUTINE_FILE)
        geometry = worker.plane_geometry(data)
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        receiver.getActualTCPSpeed.return_value = [.01, 0, 0, 0, 0, 0]
        feedback = Feedback(Path("unused.json"), data, classifier=measurement_worker.classify_plane)
        feedback.attach(receiver)
        with patch("src.program.webapp2.feedback.write_json_atomic"):
            for x, y in [(100, -20), (200, -50), (geometry["taught_length"] + 50, -30)]:
                receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(data, geometry, x, y, allow_x_outside_taught_range=True)
                feedback.sample()
                self.assertTrue(feedback.last["in_measurement_plane"])
                self.assertAlmostEqual(feedback.last["measurement_xy"]["X"], x)
                self.assertAlmostEqual(feedback.last["measurement_xy"]["Y"], y)
            receiver.getActualTCPPose.return_value = data["waypoints"]["p_start_h"]["p"]
            feedback.sample()
            self.assertFalse(feedback.last["in_measurement_plane"])

    def test_failed_publish_does_not_kill_sampling_loop(self):
        feedback = Feedback(Path("unused.json"), {})
        feedback.finished = Mock()
        feedback.finished.wait.side_effect = [False, False, False, True]
        with patch.object(feedback, "sample", side_effect=[PermissionError("Locked"), PermissionError("Locked"), None]) as sample, patch("builtins.print") as warning:
            feedback._run()
        self.assertEqual(sample.call_count, 3)
        warning.assert_called_once()

    def test_tcp_and_xy_are_published_before_flexible_move_finishes(self):
        data = read_routines_file(ROUTINE_FILE)
        geometry = worker.plane_geometry(data)
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(data, geometry, 0, 0)
        receiver.getActualTCPSpeed.return_value = [.01, 0, 0, 0, 0, 0]
        samples = []
        move_finished = False

        def publish(path, result):
            if result.get("measurement_xy"):
                samples.append((move_finished, result["tcp_position"], result["measurement_xy"]))

        def move(*args):
            nonlocal move_finished
            for x in (100, 200, 300):
                receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(data, geometry, x, -20)
                time.sleep(.3)
            move_finished = True
            receiver.getActualTCPSpeed.return_value = [0] * 6

        feedback = Feedback(Path("unused.json"), data, classifier=worker.classify_plane)
        feedback.attach(receiver)
        with patch("src.program.webapp2.feedback.write_json_atomic", side_effect=publish), patch.object(worker, "wait_until_tcp_stops"), patch.object(worker.flexible, "movel_pose", side_effect=move):
            feedback.start()
            try:
                worker.perform_action({"action": "move", "x": 300, "y": -20}, receiver, data, geometry, Path("unused-state.json"))
            finally:
                feedback.close()
        intermediate = [(tcp, xy) for finished, tcp, xy in samples if not finished and 0 < xy["X"] < 300 - 1e-6]
        self.assertGreaterEqual(len(intermediate), 2)
        self.assertGreater(len({round(xy["X"]) for tcp, xy in intermediate}), 1)
        self.assertGreater(len({round(tcp["X"]) for tcp, xy in intermediate}), 1)


class AutomaticFailureRegressionTests(unittest.TestCase):
    def test_status_tracks_active_point_detour_and_exit_during_actions(self):
        import run_measurements as automatic
        data = read_routines_file(ROUTINE_FILE)
        config = deepcopy(worker.flexible.MEASUREMENT_CONFIG)
        config["line"].update(auto_fit=False, x_start=0, increment=100, number_of_measurements=3)
        config["measurement"]["hold_duration"] = 2.75
        config["obstacle"] = {"start": 40, "end": 60}
        receiver = Mock()
        receiver.getActualTCPPose.return_value = data["waypoints"]["p_start_h"]["p"]
        states = []
        actions = []

        def capture(path, state):
            states.append(deepcopy(state))

        def force(*args, **kwargs):
            self.assertEqual(kwargs["hold_duration"], 2.75)
            before = deepcopy(states[-1])
            kwargs["on_force_success"]("test")
            after = states[-1]
            self.assertEqual(after["active_point"], before["active_point"])
            self.assertFalse(after["point_completed"])
            actions.append(("force", before))
            return True, "test"

        def detour(*args, **kwargs):
            actions.append(("detour", deepcopy(states[-1])))
            return "low"

        def translate(*args, **kwargs):
            actions.append(("translate", deepcopy(states[-1])))

        with ExitStack() as stack:
            for name in ("ensure_at_tcp_target", "movel_pose"):
                stack.enter_context(patch.object(automatic, name))
            stack.enter_context(patch.object(automatic, "translate_along_line", side_effect=translate))
            stack.enter_context(patch.object(automatic, "write_state", side_effect=capture))
            stack.enter_context(patch.object(automatic, "apply_force", side_effect=force))
            stack.enter_context(patch.object(automatic, "safe_avoid_obstacle", side_effect=detour))
            stack.enter_context(patch.object(automatic, "high_to_low", side_effect=lambda *a: actions.append(("entry", deepcopy(states[-1])))))
            automatic._run_measurements("test", receiver, config, "unused.json", data)
        self.assertEqual(actions[0][1]["activity"], "entry_routine")
        self.assertEqual([state["active_point"] for name, state in actions if name == "force"], [1, 2, 3])
        self.assertEqual([state["activity"] for name, state in actions if name == "detour"], ["obstacle_avoidance"])
        self.assertEqual([state["active_point"] for name, state in actions if name == "detour"], [2])
        self.assertEqual(next(state["active_point"] for name, state in actions if name == "translate"), 3)
        self.assertEqual([state["active_point"] for state in states if state.get("point_completed")], [1, 2, 3])
        self.assertTrue(any(state.get("activity") == "exit_routine" for state in states))
        self.assertEqual(states[-1]["mode"], "measurements_done")

    def test_automatic_contact_failure_still_recovers_and_ends_measurement(self):
        import run_measurements as automatic
        data = read_routines_file(ROUTINE_FILE)
        config = deepcopy(worker.flexible.MEASUREMENT_CONFIG)
        receiver = Mock()
        receiver.getActualTCPPose.return_value = data["waypoints"]["p_start_h"]["p"]
        with patch.object(automatic, "assert_robot_running"), patch.object(automatic, "high_to_low"), patch.object(automatic, "ensure_at_tcp_target"), patch.object(automatic, "apply_force", return_value=(False, "test-time")) as force, patch.object(automatic, "recover_after_force_limit", return_value=("start", 0)) as recover, patch.object(automatic, "write_state") as publish, patch.object(automatic, "stop_robot") as stop:
            with self.assertRaises(automatic.MeasurementUnavailableError):
                automatic.run_measurements("test-robot", receiver, config, "unused-state.json", data)
            force.assert_called_once()
            recover.assert_called_once()
            stop.assert_called_once()
            self.assertEqual(publish.call_args.args[1]["mode"], "measurement_failed")


if __name__ == "__main__":
    unittest.main()
