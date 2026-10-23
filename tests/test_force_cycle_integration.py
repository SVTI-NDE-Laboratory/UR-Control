"""Force defaults, form schema, and stationary simulation protocol checks."""

from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import Mock

from test_apply_force_script import RobotStub, SCRIPT
from src.program.webapp2 import server
from measurement_config import canonical_config, validate_force_config
from webapp.config_form import form_html


class ForceCycleIntegrationTests(unittest.TestCase):
    def test_production_force_source_matches_reviewed_script(self):
        reviewed = Path(__file__).resolve().parents[1] / 'visualize_force/scripts/apply_force_from_ur_settling.script'
        def normalized(path):
            return '\n'.join(line.rstrip() for line in path.read_text(encoding='utf-8').splitlines())
        self.assertEqual(normalized(SCRIPT), normalized(reviewed))
        self.assertEqual(normalized(SCRIPT.with_name('apply_force_from_ur_settling.script')), normalized(reviewed))

    def test_simulation_uses_only_timers_and_registers(self):
        for delay in (0, .5, 2.5):
            with self.subTest(delay=delay):
                robot = RobotStub(ack_after=4)
                forbidden = Mock(side_effect=AssertionError('Stationary simulation must not inspect force or move'))
                reads = []

                def read_float(register):
                    reads.append(register)
                    return {43: .05, 44: delay, 45: 200}[register]

                result = robot.run(SCRIPT.with_name('apply_force_simulation.script'), {
                    'read_input_float_register': read_float,
                    **{name: forbidden for name in ('get_actual_tcp_pose', 'get_tcp_force', 'zero_ftsensor',
                                                   'force_mode', 'end_force_mode', 'movel', 'stopl')},
                })
                self.assertEqual(reads, [43, 44, 45])
                self.assertEqual(robot.statuses, [0, 1, 0])
                self.assertGreaterEqual(result['approach_elapsed'], 1)
                self.assertGreaterEqual(result['settling_elapsed'], delay)
                self.assertTrue(result['force_ready'])
                self.assertEqual(robot.hold_ticks, 4)
                forbidden.assert_not_called()

    def test_simulation_waits_for_client_release(self):
        robot = RobotStub(ack_after=None)
        with self.assertRaisesRegex(AssertionError, 'test budget'):
            robot.run(SCRIPT.with_name('apply_force_simulation.script'))
        self.assertEqual(robot.statuses, [0, 1])
        self.assertEqual(robot.force_calls, 0)

    def test_old_force_config_migrates_to_one_target(self):
        config = server.legacy.load_default_config('point_to_point')
        old = deepcopy(config)
        old['measurement'].pop('target_force')
        old['measurement'].pop('settling_time')
        old['measurement'].pop('simulation_program_path')
        old['measurement'].update(contact_threshold=140, holding_force=240)
        updated = canonical_config(old)['measurement']
        self.assertEqual(updated['target_force'], 240)
        self.assertEqual(updated['settling_time'], 1.5)
        self.assertTrue(updated['simulation_program_path'].endswith('/apply_force_simulation.urp'))
        self.assertNotIn('contact_threshold', updated)
        self.assertNotIn('holding_force', updated)
        self.assertIn('contact_threshold', old['measurement'])

    def test_force_form_and_flexible_request_have_only_one_force(self):
        config = server.legacy.load_default_config('point_to_point')
        page = form_html(config)
        self.assertIn('measurement.target_force', page)
        self.assertIn('measurement.settling_time', page)
        self.assertNotIn('contact_threshold', page)
        self.assertNotIn('holding_force', page)
        request = server.FlexibleRequest(action='force', force=200, settling_time=2.5, simulation=True)
        self.assertEqual(request.settling_time, 2.5)
        with self.assertRaises(ValueError):
            server.FlexibleRequest(action='force', threshold=100)

    def test_settling_and_target_validation(self):
        config = server.legacy.load_default_config('point_to_point')
        for key, value in [('target_force', 0), ('target_force', float('nan')),
                           ('settling_time', -1), ('settling_time', float('inf')),
                           ('simulation_program_path', '')]:
            candidate = deepcopy(config)
            candidate['measurement'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_force_config(candidate)
        config['measurement']['settling_time'] = 0
        validate_force_config(config)


if __name__ == '__main__':
    unittest.main()
