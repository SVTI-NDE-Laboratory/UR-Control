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
                  safety_error=False, hold_duration=0.5, simulation=True,
                  ready_delay=.1, settling_time=1.5, return_error=0):
        clock = Clock()
        io = Mock()
        receiver = Mock()
        receiver.getActualTCPPose.side_effect = [[0.] * 6, [return_error, 0., 0., 0., 0., 0.]]
        receiver.getActualTCPSpeed.return_value = [0.] * 6
        reached_at = ready_delay
        acknowledged_at = None

        def status(register):
            self.assertEqual(register, 42)
            if clock.now < reached_at:
                return 0
            release_start = acknowledged_at
            if release_start is not None and clock.now >= release_start + completion_delay:
                return terminal_status
            return 1

        def write_integer(register, value):
            nonlocal acknowledged_at
            self.assertTrue(42 <= register <= 46, "RTDE upper integer range exceeded")
            if register == 42 and value == 1:
                if not feedback:
                    self.assertGreaterEqual(clock.now + 1e-9, reached_at + hold_duration)
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
            load = stack.enter_context(patch.object(force, "load_and_play_urp"))
            stop = stack.enter_context(patch.object(force, "stop_robot"))
            verify = stack.enter_context(patch.object(force, "ensure_at_tcp_target", return_value=[0.] * 6))
            stack.enter_context(patch.object(force, "RETURN_TIMEOUT", 6.0))
            stack.enter_context(patch("builtins.print"))
            try:
                result = force.apply_force(
                    "test", "test.urp", 50, 160, simulation=simulation,
                    simulation_program_path="simulation.urp", settling_time=settling_time,
                    stop_method="client_feedback" if feedback else "timer",
                    acquire_data=(lambda context: {}) if feedback else None,
                    hold_duration=hold_duration,
                )
            except Exception:
                stop.assert_called_once_with("test")
                verify.assert_not_called()
                raise
            else:
                self.assertTrue(result[0])
                load.assert_called_once_with("test", "simulation.urp" if simulation else "test.urp")
                self.assertEqual({item.args[0]: item.args[1] for item in io.setInputDoubleRegister.call_args_list},
                                 {43: .05, 44: settling_time, 45: 160})
                self.assertGreaterEqual(clock.now, reached_at + completion_delay)
                stop.assert_not_called()
                if simulation:
                    verify.assert_not_called()
                else:
                    verify.assert_called_once()
                    self.assertEqual(verify.call_args.args[2], [0.] * 6)
            finally:
                self.assertEqual({call.args[0] for call in io.setInputDoubleRegister.call_args_list}, {43, 44, 45})
                self.assertTrue(all(42 <= call.args[0] <= 46 for call in io.setInputIntRegister.call_args_list))
                receiver.disconnect.assert_called_once()
                io.disconnect.assert_called_once()
                self.assertEqual(io.setInputIntRegister.call_args_list[-1].args, (42, 0))
                self.assertEqual({item.args[0] for item in io.setInputIntRegister.call_args_list}, {42})
        return clock

    def test_timer_mode_completes_without_observable_return_motion(self):
        self.run_cycle()

    def test_real_force_selects_real_urp_and_allows_stationary_settling(self):
        self.run_cycle(simulation=False, ready_delay=4, settling_time=2.5)

    def test_python_timer_can_exceed_return_allowance_before_release(self):
        self.run_cycle(hold_duration=10, completion_delay=0.5)

    def test_controller_rejecting_settings_aborts_immediately(self):
        with self.assertRaisesRegex(ValueError, "settings"):
            self.run_cycle(terminal_status=4)

    def test_simulation_force_guard_stops_without_return_correction(self):
        with self.assertRaisesRegex(RuntimeError, "40 N force guard"):
            self.run_cycle(terminal_status=5)

    def test_simulation_motion_timeout_stops_without_return_correction(self):
        with self.assertRaisesRegex(TimeoutError, "Simulation motion timed out"):
            self.run_cycle(terminal_status=6)

    def test_simulation_readiness_deadline_includes_configured_travel(self):
        self.run_cycle(ready_delay=12, settling_time=1.5)

    def test_simulation_return_error_never_triggers_unguarded_correction(self):
        with self.assertRaisesRegex(RuntimeError, "automatic correction disabled"):
            self.run_cycle(return_error=.002)

    def test_feedback_release_can_complete_without_observable_return_motion(self):
        self.run_cycle(feedback=True)

    def test_missing_completion_still_times_out_and_stops_robot(self):
        with self.assertRaisesRegex(TimeoutError, "timed out during return.*9.5 s"):
            self.run_cycle(completion_delay=100)

    def test_controller_acknowledgement_timeout_is_reported_immediately(self):
        with self.assertRaisesRegex(TimeoutError, "waiting for acknowledgement"):
            self.run_cycle(terminal_status=3)

    def test_protective_stop_during_stationary_hold_still_aborts(self):
        with self.assertRaisesRegex(RuntimeError, "protective stop"):
            self.run_cycle(safety_error=True)


if __name__ == "__main__":
    unittest.main()
