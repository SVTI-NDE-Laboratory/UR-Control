"""Execute the new URScript control flow with deterministic force histories.

Uses the existing lightweight translator; does not emulate controller dynamics
or validate syntax using an actual UR controller.
"""

import math
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_apply_force_script import translated_script


SCRIPT = Path(__file__).parent / 'scripts' / 'apply_force_std_settling.script'


class Cycle:
    def __init__(self, force=None, percent=2, step=.01, python_release=False, travel=None):
        self.step = step
        self.percent = percent
        self.force = force or (lambda self: 280.0)
        self.travel = travel or (lambda self: 0.0)
        self.python_release = python_release
        self.ticks = 0
        self.ready_tick = None
        self.target_tick = None
        self.std_tick = None
        self.force_active = False
        self.returned = False
        self.statuses = []
        self.namespace = {}

    def sync(self):
        if self.namespace.get('target_reached_once') and self.target_tick is None:
            self.target_tick = self.ticks
        if self.namespace.get('moving_force_std', -1) >= 0 and self.std_tick is None:
            self.std_tick = self.ticks
        if self.namespace.get('force_ready') and self.ready_tick is None:
            self.ready_tick = self.ticks
        self.ticks += 1
        if self.ticks > 10000:
            raise AssertionError('Cycle exceeded test budget')

    def mode(self, frame, selection, wrench, mode, limits):
        self.assert_valid_mode = (selection == [0, 0, 1, 0, 0, 0]
                                  and wrench == [0, 0, 280.0, 0, 0, 0] and mode == 2)
        assert self.assert_valid_mode
        self.force_active = True

    def end_mode(self):
        self.force_active = False

    def return_move(self, target, **kwargs):
        assert not self.force_active
        assert target == [0.0] * 6
        self.returned = True

    def input_register(self, register):
        assert self.python_release, 'Timed mode must not access registers'
        assert register == 42
        return int(self.ready_tick is not None and self.ticks - self.ready_tick >= 5)

    def output_register(self, register, value):
        assert self.python_release, 'Timed mode must not access registers'
        assert register == 42
        if value == 1:
            assert self.namespace['force_ready']
            assert self.namespace['moving_force_std'] >= 0
        self.statuses.append(value)

    def run(self):
        self.namespace.update({
            'get_steptime': lambda: self.step,
            'ceil': math.ceil, 'sqrt': math.sqrt,
            'get_actual_tcp_pose': lambda: [0.0, 0.0, self.travel(self), 0.0, 0.0, 0.0],
            'get_tcp_force': lambda: [0.0, 0.0, self.force(self), 0.0, 0.0, 0.0],
            'pose_inv': lambda p: [-v for v in p],
            'pose_trans': lambda a, b: [x + y for x, y in zip(a, b)],
            'zero_ftsensor': lambda: None, 'sleep': lambda value: None,
            'sync': self.sync, 'force_mode': self.mode,
            'end_force_mode': self.end_mode, 'stopl': lambda value: None,
            'movel': self.return_move,
            'read_input_integer_register': self.input_register,
            'write_output_integer_register': self.output_register,
        })
        source = SCRIPT.read_text(encoding='utf-8')
        source = source.replace('std_percent = 2.0', f'std_percent = {self.percent:.1f}')
        source = source.replace('hold_duration = 3.0', 'hold_duration = 0.3')
        source = source.replace('use_python_release = False', f'use_python_release = {self.python_release}')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / SCRIPT.name
            target.write_text(source, encoding='utf-8')
            exec(translated_script(target), self.namespace)
        return self.namespace


class StandardDeviationScriptTests(unittest.TestCase):
    def test_gate_and_full_window_at_native_500_hz(self):
        cycle = Cycle(step=.002)
        result = cycle.run()
        self.assertEqual(cycle.target_tick, 0)
        self.assertAlmostEqual(cycle.std_tick * cycle.step, .5)
        self.assertEqual(cycle.std_tick, cycle.ready_tick)
        self.assertEqual(result['moving_force_std'], 0)
        self.assertTrue(result['contact_detected'])
        self.assertTrue(cycle.returned)

    def test_no_samples_before_target_and_later_dip_does_not_reset_buffer(self):
        cycle = Cycle(force=lambda c: 279 if c.ticks < 60 else 280 if c.ticks == 60 else 270)
        result = cycle.run()
        self.assertEqual(cycle.target_tick, 60)
        self.assertEqual(cycle.std_tick, 110)
        self.assertEqual(cycle.ready_tick, 110)
        self.assertAlmostEqual(result['measured_force_z'], 270)

    def test_5_percent_accepts_noise_that_2_percent_rejects(self):
        for percent, expected in ((5, True), (2, False)):
            with self.subTest(percent=percent):
                cycle = Cycle(force=lambda c: 290 if c.ticks % 2 == 0 else 270, percent=percent)
                result = cycle.run()
                self.assertEqual(result['force_ready'], expected)
                self.assertEqual(result['cycle_failed'], not expected)
                self.assertTrue(cycle.returned)

    def test_readiness_and_timer_do_not_reset_after_large_fluctuations(self):
        cycle = Cycle(force=lambda c: 280 if not c.namespace.get('force_ready')
                      else 500 if c.ticks % 2 else 0)
        result = cycle.run()
        self.assertTrue(result['force_ready'])
        self.assertFalse(result['cycle_failed'])
        self.assertGreater(result['moving_force_std'], result['std_limit'])
        self.assertAlmostEqual(result['hold_elapsed'], .3)
        self.assertAlmostEqual((cycle.ticks - cycle.ready_tick) * cycle.step, .3)

    def test_no_mean_force_requirement_after_first_target_crossing(self):
        cycle = Cycle(force=lambda c: 280 if c.ticks == 0 else 200)
        result = cycle.run()
        self.assertTrue(result['force_ready'])
        self.assertAlmostEqual(result['moving_force_mean'], 200)
        self.assertFalse(result['cycle_failed'])

    def test_never_reaching_target_times_out_without_hold(self):
        cycle = Cycle(force=lambda c: 279)
        result = cycle.run()
        self.assertIsNone(cycle.target_tick)
        self.assertIsNone(cycle.ready_tick)
        self.assertEqual(result['moving_force_std'], -1)
        self.assertEqual(result['hold_elapsed'], 0)
        self.assertTrue(result['cycle_failed'])
        self.assertTrue(cycle.returned)

    def test_distance_limit_also_remains_active_after_readiness(self):
        cycle = Cycle(travel=lambda c: .06 if c.ticks >= 65 else 0)
        result = cycle.run()
        self.assertIsNotNone(cycle.ready_tick)
        self.assertTrue(result['cycle_failed'])
        self.assertIn('displacement', result['failure_message'])
        self.assertTrue(cycle.returned)

    def test_python_ready_signal_and_release(self):
        cycle = Cycle(python_release=True)
        result = cycle.run()
        self.assertEqual(cycle.statuses, [0, 1, 0])
        self.assertTrue(result['force_ready'])
        self.assertFalse(result['cycle_failed'])
        self.assertTrue(cycle.returned)


if __name__ == '__main__':
    unittest.main()
