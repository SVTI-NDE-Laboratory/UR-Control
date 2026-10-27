"""Indicator state distinguishes force activity from a connected, idle receiver."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import measurement_worker
from src.program.webapp2.feedback import Feedback
from src.program.webapp2.settings import ROUTINE_FILE
from read_routines import read_routines_file


class IndicatorFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.data = read_routines_file(ROUTINE_FILE)
        self.feedback = Feedback(Path("unused-feedback.json"), self.data)
        self.receiver = Mock()
        self.receiver.getSafetyStatusBits.return_value = 0
        self.receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_start_l"]["p"]
        self.receiver.getActualQ.return_value = self.data["waypoints"]["p_start_l"]["q"]
        self.receiver.getActualTCPSpeed.return_value = [0] * 6
        patcher = patch("src.program.webapp2.feedback.write_json_atomic")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.feedback.attach(self.receiver)

    def test_connected_idle_receiver_does_not_enable_force_or_moving(self):
        self.feedback.sample()
        self.assertTrue(self.feedback.last["robot_connected"])
        self.assertFalse(self.feedback.last["force_mode"])
        self.assertFalse(self.feedback.last["moving"])

    def test_stationary_force_cycle_only_enables_force_indicator(self):
        with self.feedback.force_cycle():
            self.assertTrue(self.feedback.last["force_mode"])
            self.assertFalse(self.feedback.last["moving"])
        self.assertFalse(self.feedback.last["force_mode"])
        self.assertFalse(self.feedback.last["moving"])

    def test_force_error_clears_force_mode(self):
        with self.assertRaisesRegex(RuntimeError, "force failed"):
            with self.feedback.force_cycle():
                raise RuntimeError("force failed")
        self.assertFalse(self.feedback.force_mode)
        self.assertFalse(self.feedback.last["force_mode"])
        self.assertFalse(self.feedback.last["moving"])

    def test_motion_without_force_only_enables_moving(self):
        self.receiver.getActualTCPSpeed.return_value = [.01, 0, 0, 0, 0, 0]
        self.feedback.sample()
        self.assertTrue(self.feedback.last["moving"])
        self.assertFalse(self.feedback.last["force_mode"])

    def test_stationary_speed_noise_does_not_enable_moving(self):
        self.receiver.getActualTCPSpeed.return_value = [.0003, -.0004, .0002, .001, -.002, .001]
        self.feedback.sample()
        self.assertFalse(self.feedback.last["moving"])

    def test_motion_threshold_hysteresis_and_return_to_rest(self):
        for speed, expected in ((.0015, False), (.0025, True), (.0015, True), (.0008, False)):
            self.receiver.getActualTCPSpeed.return_value = [speed, 0, 0, 0, 0, 0]
            self.feedback.sample()
            self.assertEqual(self.feedback.last["moving"], expected)

    def test_angular_speed_has_its_own_threshold_and_release(self):
        for speed, expected in ((.008, False), (.012, True), (.008, True), (.004, False)):
            self.receiver.getActualTCPSpeed.return_value = [0, 0, 0, 0, speed, 0]
            self.feedback.sample()
            self.assertEqual(self.feedback.last["moving"], expected)

    def test_actual_motion_during_force_enables_both_indicators(self):
        self.receiver.getActualTCPSpeed.return_value = [.01, 0, 0, 0, 0, 0]
        with self.feedback.force_cycle():
            self.assertTrue(self.feedback.last["force_mode"])
            self.assertTrue(self.feedback.last["moving"])

    def test_disconnect_during_force_clears_reported_indicators(self):
        with self.feedback.force_cycle():
            self.feedback.detach()
            self.feedback.sample()
            self.assertFalse(self.feedback.last["force_mode"])
            self.assertIsNone(self.feedback.last["moving"])

    def test_automatic_worker_wraps_force_cycle_and_restores_hooks(self):
        sys.path.insert(0, str(ROOT / "src/program/commands"))
        import run_measurement_sequence as sequence
        import run_measurements as measurements

        def force(*args, **kwargs):
            self.assertTrue(self.feedback.last["force_mode"])
            self.assertFalse(self.feedback.last["moving"])
            return True, "test"

        def workflow():
            connection = sequence.get_rtde_receive("test-robot")
            self.assertEqual(measurements.apply_force("test"), (True, "test"))
            self.assertFalse(self.feedback.last["force_mode"])
            connection.disconnect()

        with tempfile.TemporaryDirectory() as directory, patch.object(sequence, "get_rtde_receive", return_value=self.receiver) as connect, patch.object(sequence, "main", side_effect=workflow), patch.object(measurements, "apply_force", side_effect=force) as apply, patch.object(measurement_worker, "Feedback", return_value=self.feedback) as feedback_factory, patch.object(sys, "argv", ["worker", "--output-dir", directory]):
            measurement_worker.main()
            self.assertIs(feedback_factory.call_args.kwargs["classifier"], measurement_worker.classify_plane)
            self.assertIs(measurements.apply_force, apply)
            self.assertIs(sequence.get_rtde_receive, connect)
            apply.assert_called_once_with("test")


if __name__ == "__main__":
    unittest.main()
