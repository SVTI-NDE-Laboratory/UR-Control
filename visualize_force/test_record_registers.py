"""Offline checks for the recorder's parameter writes and timed release protocol."""

import unittest
from unittest.mock import Mock, call, patch

from record_registers import ForceRegisters
from urp_runner import run_cycle


class RegisterRecorderTests(unittest.TestCase):
    def controller(self):
        self.io = Mock()
        self.factory = Mock(return_value=self.io)
        return ForceRegisters('robot', 200, 50, .3, self.factory)

    def test_parameter_units_and_clear_before_start(self):
        controller = self.controller()
        controller.prepare()
        self.factory.assert_called_once_with('robot', use_upper_range_registers=True)
        self.assertEqual(self.io.method_calls, [call.setInputDoubleRegister(43, .05),
                                              call.setInputDoubleRegister(44, 1.5),
                                              call.setInputDoubleRegister(45, 200),
                                              call.setInputIntRegister(42, 0)])
        controller.close()
        self.io.disconnect.assert_called_once()

    def test_custom_settling_time_is_written(self):
        controller = self.controller()
        controller.settling_time = .75
        controller.prepare()
        self.io.setInputDoubleRegister.assert_any_call(44, .75)

    def test_invalid_settling_times_are_rejected(self):
        for delay in (-1, float('nan'), float('inf')):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                ForceRegisters('robot', 200, 50, 3, settling_time=delay)

    def test_rejected_parameter_write_aborts(self):
        controller = self.controller()
        self.io.setInputDoubleRegister.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'register 43'):
            controller.prepare()
        self.io.setInputIntRegister.assert_not_called()
        controller.close()

    def test_stale_ready_is_ignored_until_initialized(self):
        controller = self.controller()
        controller.prepare()
        receiver = Mock()
        receiver.getOutputIntRegister.return_value = 1
        controller.poll(receiver)
        self.assertIsNone(controller.ready_at)
        self.assertFalse(controller.initialized)
        self.io.setInputIntRegister.assert_called_once_with(42, 0)

    def test_failure_statuses_abort(self):
        for status in (2, 3, 4):
            controller = self.controller()
            receiver = Mock()
            receiver.getOutputIntRegister.return_value = status
            with self.assertRaisesRegex(RuntimeError, f'= {status}'):
                controller.poll(receiver)

    def test_hold_ending_before_release_is_failure(self):
        controller = self.controller()
        controller.initialized = True
        controller.ready_at = 0
        receiver = Mock()
        receiver.getOutputIntRegister.return_value = 0
        with self.assertRaisesRegex(RuntimeError, 'before measurement'):
            controller.poll(receiver)

    def run_fake_cycle(self, remote=True, fail_after_ready=False):
        controller = self.controller()
        clock = [0.0]
        playing = [False]
        release = [None]
        events = []
        receiver = Mock()
        receiver.isConnected.return_value = True
        receiver.getTimestamp.side_effect = lambda: clock[0]
        receiver.getSafetyStatusBits.return_value = 1

        def output(register):
            self.assertEqual(register, 42)
            if clock[0] < .2:
                return 0
            if fail_after_ready and clock[0] >= .4:
                return 2
            if release[0] is not None and clock[0] >= release[0] + .2:
                return 0
            return 1

        receiver.getOutputIntRegister.side_effect = output

        def write(register, value):
            if value == 1:
                release[0] = clock[0]
            return True

        self.io.setInputIntRegister.side_effect = write

        def command(value):
            events.append(value)
            if value == 'is in remote control':
                return 'true' if remote else 'false'
            if value == 'robotmode':
                return 'Robotmode: RUNNING'
            if value.startswith('load '):
                return 'Loading program: test.urp'
            if value == 'play':
                self.io.setInputIntRegister.assert_called_once_with(42, 0)
                playing[0] = True
                return 'Starting program'
            if value == 'stop':
                return 'Stopped'
            if value == 'programState':
                done = release[0] is not None and clock[0] >= release[0] + .3
                return 'PLAYING' if playing[0] and not done else 'STOPPED'
            raise AssertionError(value)

        def sleep(seconds):
            clock[0] += seconds

        self.events = events
        with patch('urp_runner.time.monotonic', side_effect=lambda: clock[0]), \
                patch('urp_runner.time.sleep', side_effect=sleep):
            try:
                result = run_cycle(receiver, 'robot', 'test.urp', .05, .05, 2,
                                   command, controller)
            finally:
                controller.close()
        return result, controller, release[0]

    def test_full_cycle_releases_only_after_ready_plus_duration(self):
        result, controller, release = self.run_fake_cycle()
        self.assertEqual(result, 'program_stopped')
        self.assertGreaterEqual(release - controller.ready_at, .3)
        self.assertTrue(controller.completed)
        self.assertNotIn('stop', self.events)
        self.io.disconnect.assert_called_once()

    def test_preflight_failure_does_not_write_registers(self):
        with self.assertRaisesRegex(RuntimeError, 'Remote Control'):
            self.run_fake_cycle(remote=False)
        self.factory.assert_not_called()
        self.io.setInputIntRegister.assert_not_called()

    def test_force_failure_stops_program_without_releasing(self):
        with self.assertRaisesRegex(RuntimeError, '= 2'):
            self.run_fake_cycle(fail_after_ready=True)
        self.assertEqual(self.events[-1], 'stop')
        self.io.setInputIntRegister.assert_called_once_with(42, 0)

    def test_program_stop_without_handshake_is_failure(self):
        controller = self.controller()
        with self.assertRaisesRegex(RuntimeError, 'handshake'):
            controller.finish(Mock())


if __name__ == '__main__':
    unittest.main()
