"""Route inference and confirmation must never silently bypass taught paths."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import manual_worker as worker, server
from src.program.webapp2.control import ControlWorkers
from src.program.webapp2.settings import ROUTINE_FILE
from src.program.webapp2.waypoint_routes import routine_transitions, waypoint_warning, waypoint_motion_options, waypoint_motion_limits
from read_routines import read_routines_file


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.data = {"routines": [{"name": "out", "steps": [
            {"waypoint": "Home", "motion": {"type": "j"}},
            {"waypoint": "middle", "motion": {"type": "j"}},
            {"waypoint": "end", "motion": {"type": "l"}},
        ]}]}

    def test_only_consecutive_neighbors_with_matching_motion_are_supported(self):
        self.assertIsNone(waypoint_warning(self.data, "Home", "middle", "j"))
        self.assertIsNone(waypoint_warning(self.data, "middle", "end", "l"))
        self.assertIsNone(waypoint_warning(self.data, "middle", "Home", "j"))
        self.assertIsNone(waypoint_warning(self.data, "end", "middle", "l"))
        for source, target, motion in [("Home", "end", "j"), ("end", "Home", "l"),
                                       ("Home", "middle", "l"), ("middle", "Home", "l"),
                                       ("end", "middle", "j"), (None, "end", "l")]:
            self.assertIsNotNone(waypoint_warning(self.data, source, target, motion))
        self.assertEqual(len(routine_transitions(self.data)), 4)

    def test_linear_default_is_50(self):
        request = server.ManualRequest(action="waypoint", waypoint="p_start_h")
        self.assertEqual(request.speed, 50)

    def test_manual_motion_restrictions_override_available_coordinates(self):
        both = {"p": [0] * 6, "q": [0] * 6}
        for name in ("Home", "home_to_start1", "home_to_start2", "end_to_home1"):
            self.assertEqual(waypoint_motion_options(name, both), {"linear": False, "joint": True})
        for name in ("p_start_l", "p_end_l"):
            self.assertEqual(waypoint_motion_options(name, both), {"linear": True, "joint": False})
        for name in ("p_start_h", "p_end_h"):
            self.assertEqual(waypoint_motion_options(name, both), {"linear": True, "joint": True})
        self.assertEqual(waypoint_motion_options("p_start_h", {"q": [0] * 6}), {"linear": False, "joint": True})

    def test_high_low_pairs_are_supported_linear_moves_in_both_directions(self):
        self.data["waypoints"] = {name: {} for name in ("p_start_h", "p_start_l", "p_end_h", "p_end_l")}
        for high, low in (("p_start_h", "p_start_l"), ("p_end_h", "p_end_l")):
            for source, target in ((high, low), (low, high)):
                self.assertIsNone(waypoint_warning(self.data, source, target, "l"))
                self.assertIsNotNone(waypoint_warning(self.data, source, target, "j"))
        self.assertIsNotNone(waypoint_warning(self.data, "p_start_h", "p_end_l", "l"))

    def test_high_low_pair_requires_both_points_to_exist(self):
        self.data["waypoints"] = {"p_start_h": {}}
        self.assertIsNotNone(waypoint_warning(self.data, "p_start_h", "p_start_l", "l"))


class MotionLimitTests(unittest.TestCase):
    def setUp(self):
        self.data = {"waypoints": {"p_start_h": {"p": [0] * 6, "q": [0] * 6}}, "routines": [
            {"name": "first", "steps": [
                {"motion": {"type": "j", "speed": 2.0, "acceleration": 0.4}},
                {"motion": {"type": "l", "speed": 250, "acceleration": 80}}]},
            {"name": "second", "steps": [
                {"motion": {"type": "j", "speed": 1.0, "acceleration": 0.8}},
                {"motion": {"type": "l", "speed": 100, "acceleration": 300}}]}]}

    def test_independent_maxima_across_all_routines_and_matching_api_options(self):
        expected = {"j": {"speed": 2.0, "acceleration": 0.8}, "l": {"speed": 250, "acceleration": 300}}
        self.assertEqual(waypoint_motion_limits(self.data), expected)
        # Options also need waypoint names for their routine summaries.
        for routine in self.data["routines"]:
            for step in routine["steps"]:
                step["waypoint"] = "p_start_h"
        with patch.object(server, "read_routines_file", return_value=self.data):
            self.assertEqual(server.options()["motion_limits"], expected)

    def test_validator_accepts_maxima_and_rejects_excess_for_each_quantity(self):
        with patch.object(server, "read_routines_file", return_value=self.data):
            for motion, limits in waypoint_motion_limits(self.data).items():
                request = {"action": "waypoint", "waypoint": "p_start_h", "motion": motion, **limits}
                server.ManualRequest(**request)
                for field in ("speed", "acceleration"):
                    with self.subTest(motion=motion, field=field):
                        with self.assertRaisesRegex(ValueError, "Manual limits"):
                            server.ManualRequest(**{**request, field: limits[field] + 0.01})

    def test_lower_routine_limits_replace_manual_caps(self):
        self.data["routines"] = [{"steps": [{"motion": {"type": "l", "speed": 20, "acceleration": 30}}]}]
        self.assertEqual(waypoint_motion_limits(self.data), {
            "l": {"speed": 20, "acceleration": 30}, "j": {"speed": 0.5, "acceleration": 0.5}})
        with patch.object(server, "read_routines_file", return_value=self.data):
            with self.assertRaisesRegex(ValueError, "Manual limits"):
                server.ManualRequest(action="waypoint", waypoint="p_start_h", speed=21, acceleration=30)


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data = read_routines_file(ROUTINE_FILE)
        self.receiver = Mock()
        self.receiver.getSafetyStatusBits.return_value = 0
        self.receiver.getActualQ.return_value = self.data["waypoints"]["Home"]["q"]
        self.receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_start_l"]["p"]
        self.receiver.getActualTCPSpeed.return_value = [0] * 6
        self.request = {"action": "waypoint", "waypoint": "p_start_h", "motion": "j",
                        "speed": .05, "acceleration": .1}

    def run_with_decision(self, proceed, changed=False):
        states = []
        with patch.object(worker, "Feedback"), patch.object(worker, "assert_robot_running"), patch.object(worker, "get_rtde_receive", return_value=self.receiver), patch.object(worker, "stop_robot"), patch.object(worker, "movej") as move, patch.object(worker, "movel_pose") as linear:
            def publish(path, state):
                states.append(state)
                if state["mode"] == "waiting_for_waypoint_confirmation":
                    move.assert_not_called()
                    linear.assert_not_called()
                    (self.directory / "waypoint_confirmation.json").write_text(json.dumps({"proceed": proceed}))
                    if changed:
                        pose = list(self.receiver.getActualTCPPose.return_value)
                        pose[0] += .1
                        self.receiver.getActualTCPPose.return_value = pose
            with patch.object(worker, "write_json_atomic", side_effect=publish):
                if changed:
                    with self.assertRaisesRegex(ValueError, "position changed"):
                        worker.run(self.request, self.directory)
                else:
                    worker.run(self.request, self.directory)
            if proceed and not changed:
                move.assert_called_once()
            else:
                move.assert_not_called()
            linear.assert_not_called()
        return states

    def test_skipping_points_waits_for_confirmation_and_cancel_does_not_move(self):
        states = self.run_with_decision(False)
        warning = next(state for state in states if state["mode"] == "waiting_for_waypoint_confirmation")
        self.assertEqual((warning["source"], warning["target"]), ("Home", "p_start_h"))
        self.assertEqual(states[-1]["mode"], "idle")

    def test_confirmed_direct_move_executes_after_decision(self):
        self.run_with_decision(True)

    def test_changed_position_after_confirmation_never_moves(self):
        self.run_with_decision(True, changed=True)

    def test_taught_next_step_does_not_require_confirmation(self):
        self.request["waypoint"] = "home_to_start1"
        states = self.run_with_decision(True)
        self.assertNotIn("waiting_for_waypoint_confirmation", [state["mode"] for state in states])

    def test_unknown_position_requires_confirmation(self):
        self.receiver.getActualQ.return_value = [99] * 6
        states = self.run_with_decision(False)
        warning = next(state for state in states if state["mode"] == "waiting_for_waypoint_confirmation")
        self.assertIsNone(warning["source"])

    def test_stationary_check_prevents_any_move(self):
        self.receiver.getActualTCPSpeed.return_value = [.1, 0, 0, 0, 0, 0]
        with patch.object(worker, "write_json_atomic") as publish:
            with self.assertRaisesRegex(TimeoutError, "TCP did not stop"):
                worker.check_waypoint_move(self.request, self.receiver, self.data, self.directory)
        publish.assert_not_called()

    def test_small_speed_noise_does_not_block_stopped_robot(self):
        self.receiver.getActualTCPSpeed.return_value = [.0003, -.0002, .0001, .0004, -.0002, 0]
        self.request["waypoint"] = "home_to_start1"
        with patch("robot_move.time.sleep") as sleep:
            self.assertTrue(worker.check_waypoint_move(self.request, self.receiver, self.data, self.directory))
        sleep.assert_not_called()

    def test_recent_motion_can_settle_before_checking_route(self):
        samples = iter([[.01, 0, 0, 0, 0, 0], [.004, 0, 0, 0, 0, 0]])
        self.receiver.getActualTCPSpeed.side_effect = lambda: next(samples, [.0003, 0, 0, 0, 0, 0])
        self.request["waypoint"] = "home_to_start1"
        self.assertTrue(worker.check_waypoint_move(self.request, self.receiver, self.data, self.directory))

    def test_speed_noise_after_confirmation_does_not_block_move(self):
        self.receiver.getActualTCPSpeed.return_value = [.0003, 0, 0, .0004, 0, 0]
        self.run_with_decision(True)

    def test_missing_confirmation_times_out_without_moving(self):
        with patch.object(worker, "wait_until_tcp_stops"), patch.object(worker, "write_json_atomic"), patch.object(worker.time, "monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(TimeoutError, "No waypoint move"):
                worker.check_waypoint_move(self.request, self.receiver, self.data, self.directory)

    def test_confirmation_is_bound_to_active_worker_and_consumed_once(self):
        owner = ControlWorkers()
        owner.directory = self.directory
        owner._state_file = self.directory / "state.json"
        owner._kind = "manual"
        owner._process = Mock()
        owner._process.poll.return_value = None
        owner._state_file.write_text(json.dumps({"mode": "waiting_for_waypoint_confirmation"}))
        with self.assertRaisesRegex(RuntimeError, "no longer active"):
            owner.confirm_waypoint("previous-worker/state.json", True)
        owner.confirm_waypoint(str(owner._state_file), False)
        self.assertEqual(json.loads((self.directory / "waypoint_confirmation.json").read_text()), {"proceed": False})
        with self.assertRaisesRegex(RuntimeError, "No waypoint move"):
            owner.confirm_waypoint(str(owner._state_file), True)


if __name__ == "__main__":
    unittest.main()
