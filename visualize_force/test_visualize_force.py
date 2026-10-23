"""Offline numerical, CSV recovery, lifecycle, and UR cycle checks."""

import csv
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from force_frames import convert, force_in_tool
from record import capture
from urp_runner import program_path, run_cycle


class FrameTests(unittest.TestCase):
    def test_base_x_becomes_tool_z_at_positive_y_quarter_turn(self):
        rotated = force_in_tool((20, 3, 4), (0, math.pi / 2, 0))
        for actual, expected in zip(rotated, (-4, 3, 20)):
            self.assertAlmostEqual(actual, expected)

    def test_identity_and_arbitrary_rotation_preserve_norm(self):
        self.assertEqual(force_in_tool((1, 2, 3), (0, 0, 0)), (1, 2, 3))
        self.assertAlmostEqual(math.hypot(*force_in_tool((1, -2, 3), (.2, -.4, .5))), math.sqrt(14))

    def test_csv_conversion_timestamps_rotation_and_raw_preservation(self):
        for delimiter in (',', ';'):
            with self.subTest(delimiter=delimiter), tempfile.TemporaryDirectory() as folder:
                raw, output = Path(folder) / 'raw.csv', Path(folder) / 'force.csv'
                with raw.open('w', newline='') as stream:
                    writer = csv.writer(stream, delimiter=delimiter)
                    writer.writerow(['timestamp'] + [f'actual_TCP_{name}_{i}'
                                     for name in ('force', 'pose') for i in range(6)])
                    for stamp in (10, 10, 10.03):
                        writer.writerow([stamp, 20, 3, 4, 0, 0, 0, 1, 2, 3, 0, math.pi / 2, 0])
                before = raw.read_bytes()
                summary = convert(raw, output)
                self.assertEqual(summary['samples'], 2)
                self.assertEqual(summary['duplicate_timestamps_removed'], 1)
                with output.open() as stream:
                    reader = csv.DictReader(stream)
                    rows = list(reader)
                    self.assertEqual(reader.fieldnames[:8], ['timestamp', 'elapsed_s']
                                     + [f'actual_TCP_pose_{i}' for i in range(6)])
                for row in rows:
                    for value in row.values():
                        self.assertRegex(value, r'^-?\d+\.\d{3}$')
                self.assertAlmostEqual(float(rows[-1]['force_tool_z_N']), 20)
                self.assertAlmostEqual(float(rows[-1]['sample_dt_s']), .03)
                self.assertEqual(before, raw.read_bytes())
                with self.assertRaises(FileExistsError):
                    convert(raw, output)

    def test_empty_raw_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            raw = Path(folder) / 'raw.csv'
            raw.touch()
            with self.assertRaisesRegex(ValueError, 'empty'):
                convert(raw, Path(folder) / 'force.csv')


class RecordingTests(unittest.TestCase):
    def receiver(self):
        receiver = Mock()
        receiver.startFileRecording.return_value = True
        receiver.stopFileRecording.return_value = True
        receiver.getTimestamp.return_value = 1.0
        return receiver

    def test_duration_finalizes_and_disconnects(self):
        receiver = self.receiver()
        self.assertEqual(capture(receiver, 'unused.csv', [], 0), 'duration_completed')
        receiver.stopFileRecording.assert_called_once()
        receiver.disconnect.assert_called_once()

    def test_disconnect_finalizes_partial_recording(self):
        receiver = self.receiver()
        receiver.isConnected.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'connection lost'):
            capture(receiver, 'unused.csv', [], None)
        receiver.stopFileRecording.assert_called_once()
        receiver.disconnect.assert_called_once()

    def test_failed_start_still_disconnects(self):
        receiver = self.receiver()
        receiver.startFileRecording.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'could not start'):
            capture(receiver, 'unused.csv', [], None)
        receiver.stopFileRecording.assert_not_called()
        receiver.disconnect.assert_called_once()

    def test_ctrl_c_finalizes(self):
        receiver = self.receiver()
        receiver.isConnected.side_effect = KeyboardInterrupt
        self.assertEqual(capture(receiver, 'unused.csv', [], None), 'user_stop')
        receiver.stopFileRecording.assert_called_once()
        receiver.disconnect.assert_called_once()

    def test_automatic_cycle_runs_inside_recording(self):
        receiver = self.receiver()

        def cycle(active):
            self.assertIs(active, receiver)
            receiver.startFileRecording.assert_called_once()
            receiver.stopFileRecording.assert_not_called()
            return 'program_stopped'

        self.assertEqual(capture(receiver, 'unused.csv', [], None, cycle=cycle), 'program_stopped')
        receiver.stopFileRecording.assert_called_once()
        receiver.disconnect.assert_called_once()


class URPRunnerTests(unittest.TestCase):
    def run_fake(self, states, *, play_reply='Starting program', timeout=60, remote='true',
                 urp='test.urp', load_replies=None):
        clock = [0.0]
        events = []
        states = iter(states)
        timestamps = iter(range(10000))
        load_replies = iter(load_replies) if load_replies is not None else None
        receiver = Mock()
        receiver.isConnected.return_value = True
        receiver.getTimestamp.side_effect = lambda: next(timestamps)
        receiver.getSafetyStatusBits.return_value = 1

        def command(value):
            events.append((clock[0], value))
            if value == 'programState':
                return next(states)
            if value.startswith('load '):
                return next(load_replies) if load_replies is not None else f'Loading program: {urp}'
            return {'is in remote control': remote, 'robotmode': 'Robotmode: RUNNING',
                    'load test.urp': 'Loading program: test.urp', 'play': play_reply,
                    'stop': 'Stopped'}[value]

        def sleep(seconds):
            clock[0] += seconds

        self.events = events
        with patch('urp_runner.time.monotonic', side_effect=lambda: clock[0]), \
                patch('urp_runner.time.sleep', side_effect=sleep):
            result = run_cycle(receiver, 'unused', urp, .1, .2, timeout, command)
        return result, events, clock[0]

    def test_path_with_spaces_retries_quotes_before_play(self):
        path = '/programs/Users/JOBE/Tests Force/test_force_benchmark.urp'
        result, events, _ = self.run_fake(
            ['STOPPED'] * 3 + ['PLAYING', 'STOPPED'], urp=path,
            load_replies=['could not understand: load ' + path, 'Loading program: ' + path])
        commands = [value for _, value in events]
        self.assertEqual(result, 'program_stopped')
        self.assertLess(commands.index(f'load {path}'), commands.index(f'load "{path}"'))
        self.assertLess(commands.index(f'load "{path}"'), commands.index('play'))

    def test_both_load_rejections_never_play(self):
        with self.assertRaisesRegex(RuntimeError, 'Unquoted path:.*Quoted path:'):
            self.run_fake(['STOPPED'], urp='Tests Force/test.urp',
                          load_replies=['could not understand: raw', 'could not understand: quoted'])
        self.assertNotIn('play', [value for _, value in self.events])

    def test_missing_file_does_not_retry_or_play(self):
        with self.assertRaisesRegex(RuntimeError, 'File not found'):
            self.run_fake(['STOPPED'], urp='Tests Force/test.urp',
                          load_replies=['File not found: test.urp'])
        commands = [value for _, value in self.events]
        self.assertEqual(sum(value.startswith('load ') for value in commands), 1)
        self.assertNotIn('play', commands)

    def test_load_play_pre_roll_and_post_roll(self):
        result, events, end = self.run_fake(['STOPPED'] * 3 + ['PLAYING', 'STOPPED'])
        self.assertEqual(result, 'program_stopped')
        play_time = next(t for t, value in events if value == 'play')
        self.assertGreaterEqual(play_time, .1)
        self.assertGreaterEqual(end - events[-1][0], .2 - 1e-9)
        self.assertNotIn('stop', [value for _, value in events])

    def test_no_remote_control_does_not_load_or_play(self):
        with self.assertRaisesRegex(RuntimeError, 'Remote Control'):
            self.run_fake([], remote='false')
        self.assertFalse(any(value in ('play', 'stop') or value.startswith('load ')
                             for _, value in self.events))

    def test_existing_program_is_not_replaced(self):
        with self.assertRaisesRegex(RuntimeError, 'running or paused'):
            self.run_fake(['PLAYING'])
        self.assertNotIn('load test.urp', [value for _, value in self.events])

    def test_ambiguous_play_error_requests_stop(self):
        with self.assertRaisesRegex(RuntimeError, 'play failed'):
            self.run_fake(['STOPPED'] * 3, play_reply='Failed to execute: play')
        self.assertEqual(self.events[-1][1], 'stop')

    def test_timeout_stops_program(self):
        with self.assertRaisesRegex(RuntimeError, 'cycle-timeout'):
            self.run_fake(['STOPPED'] * 3 + ['PLAYING'] * 20, timeout=.1)
        self.assertEqual(self.events[-1][1], 'stop')

    def test_pause_stops_program(self):
        with self.assertRaisesRegex(RuntimeError, 'paused'):
            self.run_fake(['STOPPED'] * 3 + ['PLAYING', 'PAUSED'])
        self.assertEqual(self.events[-1][1], 'stop')

    def test_path_rejects_script_and_command_injection(self):
        for path in ('file.script', 'file.urp\nplay', '"file.urp"'):
            with self.assertRaises(ValueError):
                program_path(path)


class URCycleTests(unittest.TestCase):
    def test_new_script_holds_returns_and_does_not_access_registers(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
        from test_apply_force_from_ur_script import RotatedRobot
        script = Path(__file__).parent / 'scripts' / 'apply_force_visualize.script'
        robot = RotatedRobot()
        result = robot.run(script)
        self.assertGreaterEqual(result['hold_elapsed'], 3)
        self.assertGreater(robot.force_calls, 20)
        self.assertEqual(robot.statuses, [])
        self.assertIn(('return',), robot.events)

    def test_new_script_failure_skips_hold_and_returns(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
        from test_apply_force_from_ur_script import RotatedRobot
        robot = RotatedRobot(wrench=(0, 0, 0, 0, 0, 0), travel_per_call=.06)
        result = robot.run(Path(__file__).parent / 'scripts' / 'apply_force_visualize.script')
        self.assertFalse(result['force_reached'])
        self.assertEqual(result['hold_elapsed'], 0)
        self.assertIn(('return',), robot.events)


if __name__ == '__main__':
    unittest.main()
