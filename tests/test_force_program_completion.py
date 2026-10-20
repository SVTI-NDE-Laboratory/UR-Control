"""A force-program hold is not evidence of a failed return movement."""

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import settings  # Configure the shared source paths.
import apply_force as force


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class ForceProgramCompletionTests(unittest.TestCase):
    def run_cycle(self, feedback=False, completion_delay=3.5, terminal_status=0,
                  safety_error=False):
        clock = Clock()
        io = Mock()
        receiver = Mock()
        receiver.getActualTCPPose.return_value = [0.] * 6
        receiver.getActualTCPSpeed.return_value = [0.] * 6
        reached_at = .1
        acknowledged_at = None

        def status(register):
            self.assertEqual(register, 42)
            if clock.now < reached_at:
                return 0
            release_start = acknowledged_at if feedback else reached_at
            if release_start is not None and clock.now >= release_start + completion_delay:
                return terminal_status
            return 1

        def write_integer(register, value):
            nonlocal acknowledged_at
            if register == 42 and value == 1:
                acknowledged_at = clock.now
            return True

        def check_safety(connection):
            if safety_error and clock.now >= 3.0:
                raise RuntimeError("Robot protective stop")

        receiver.getOutputIntRegister.side_effect = status
        io.setInputIntRegister.side_effect = write_integer
        with ExitStack() as stack:
            stack.enter_context(patch.object(force, "time", clock))
            stack.enter_context(patch.object(force, "RTDEIOInterface", return_value=io))
            stack.enter_context(patch.object(force, "RTDEReceiveInterface", return_value=receiver))
            stack.enter_context(patch.object(force, "assert_robot_running"))
            stack.enter_context(patch.object(force, "assert_robot_safe", side_effect=check_safety))
            stack.enter_context(patch.object(force, "load_and_play_urp"))
            stop = stack.enter_context(patch.object(force, "stop_robot"))
            verify = stack.enter_context(patch.object(force, "ensure_at_tcp_target", return_value=[0.] * 6))
            stack.enter_context(patch.object(force, "RETURN_TIMEOUT", 6.0))
            stack.enter_context(patch("builtins.print"))
            try:
                result = force.apply_force(
                    "test", "test.urp", 50, 140, 160, simulation=True,
                    acknowledge_force_hold=feedback,
                    acquire_data=(lambda context: {}) if feedback else None,
                )
            except Exception:
                stop.assert_called_once_with("test")
                verify.assert_not_called()
                raise
            else:
                self.assertTrue(result[0])
                self.assertGreaterEqual(clock.now, reached_at + completion_delay)
                stop.assert_not_called()
                verify.assert_called_once()
                self.assertEqual(verify.call_args.args[2], [0.] * 6)
            finally:
                receiver.disconnect.assert_called_once()
                io.disconnect.assert_called_once()
                self.assertEqual(io.setInputIntRegister.call_args_list[-2].args, (42, 0))
                self.assertEqual(io.setInputIntRegister.call_args_list[-1].args, (46, 0))
        return clock

    def test_time_mode_can_remain_stationary_longer_than_two_seconds(self):
        self.run_cycle()

    def test_feedback_release_can_complete_without_observable_return_motion(self):
        self.run_cycle(feedback=True)

    def test_missing_completion_still_times_out_and_stops_robot(self):
        with self.assertRaisesRegex(TimeoutError, "timed out during return.*6.0 s"):
            self.run_cycle(completion_delay=100)

    def test_controller_acknowledgement_timeout_is_reported_immediately(self):
        with self.assertRaisesRegex(TimeoutError, "waiting for acknowledgement"):
            self.run_cycle(terminal_status=3)

    def test_protective_stop_during_stationary_hold_still_aborts(self):
        with self.assertRaisesRegex(RuntimeError, "protective stop"):
            self.run_cycle(safety_error=True)


if __name__ == "__main__":
    unittest.main()
