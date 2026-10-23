"""Selection preserves original IDs and obstacle-safe routes without hardware."""
import sys
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import server
from measurement_config import canonical_config, validate_measurement_config
from measurement_plan import create_measurement_plan, first_measurable_index
from line_planner import selected_line_positions, obstacle_interval
from webapp.config_form import edited_config, form_html
import run_measurements as automatic


class PointSelectionTests(unittest.TestCase):
    def setUp(self):
        self.data = {'waypoints': {
            'p_start_l': {'p': [0, 0, 0, 0, 0, 0]},
            'p_end_l': {'p': [1, 0, 0, 0, 0, 0]},
            'p_start_h': {'p': [0, 0, -.1, 0, 0, 0]},
            'p_end_h': {'p': [1, 0, -.1, 0, 0, 0]},
        }}
        self.config = canonical_config({
            'line': {'start_point':'p_start_l', 'end_point':'p_end_l', 'x_start':0., 'x_end':1000.,
                     'offset_y':-275., 'increment':100., 'number_of_measurements':11,
                     'auto_fit':True, 'spacing_source':'increment'},
            'motion': {'type':'l', 'speed':50., 'acceleration':100.},
            'measurement': {'program_path':'force.urp', 'target_force':200., 'max_displacement':50.,
                            'settling_time':1.5, 'hold_duration':2., 'stop_method':'timer'},
            'obstacle_width':200., 'obstacle':{'start':300., 'end':500.},
        })

    def measured_ids(self):
        return [point['point_number'] for point in create_measurement_plan(self.config, self.data)['points'] if point['scheduled']]

    def fields(self):
        fields = {f'{section}.{key}':[str(value).lower()] for section in ('line','motion','measurement')
                  for key, value in self.config[section].items()}
        fields.update({'obstacle.enabled':['true'], 'obstacle.position':['450']})
        return fields

    def test_all_is_default_and_obstacle_wins(self):
        self.assertEqual(self.measured_ids(), [1,2,3,7,8,9,10,11])
        self.assertEqual(first_measurable_index(self.config, self.data), 1)

    def test_from_point_is_inclusive_and_keeps_original_ids(self):
        self.config['points_selection'] = {'mode':'from_point', 'from_point':5}
        validate_measurement_config(self.config, self.data)
        self.assertEqual(self.measured_ids(), [7,8,9,10,11])
        self.assertEqual(first_measurable_index(self.config, self.data), 7)

    def test_custom_is_spatially_ordered_and_cannot_override_obstacle(self):
        self.config['points_selection'] = {'mode':'custom', 'point_ids':[9,2,5,7]}
        validate_measurement_config(self.config, self.data)
        self.assertEqual(self.measured_ids(), [2,7,9])
        points = create_measurement_plan(self.config, self.data)['points']
        self.assertEqual(points[0]['skip_reason'], 'not_selected')
        self.assertEqual(points[4]['skip_reason'], 'obstacle')
        self.assertEqual([point['point_number'] for point in points], list(range(1,12)))

    def test_invalid_and_empty_selections_fail_before_connecting(self):
        for selection in ({'mode':'invalid'}, {'mode':'from_point','from_point':12},
                          {'mode':'from_point','from_point':True}, {'mode':'custom','point_ids':[]},
                          {'mode':'custom','point_ids':[4,5]}, {'mode':'custom','point_ids':['2']},
                          {'mode':'custom','point_ids':[2.5]}, {'mode':'custom','point_ids':[0]}):
            with self.subTest(selection=selection):
                self.config['points_selection'] = selection
                with self.assertRaises(ValueError):
                    validate_measurement_config(self.config, self.data)
                with patch.object(automatic, 'assert_robot_running') as connect, self.assertRaises(ValueError):
                    automatic.run_measurements('test', Mock(), self.config, 'unused', self.data)
                connect.assert_not_called()

    def run_mocked(self):
        receiver = Mock()
        receiver.getActualTCPPose.return_value = [0,0,-.1,0,0,0]
        with ExitStack() as stack:
            mocks = {name:stack.enter_context(patch.object(automatic,name)) for name in
                     ('high_to_low','low_to_high','ensure_at_tcp_target','write_state','movel_pose','translate_along_line')}
            mocks['force'] = stack.enter_context(patch.object(automatic,'apply_force',return_value=(True,'test')))
            mocks['avoid'] = stack.enter_context(patch.object(automatic,'safe_avoid_obstacle',return_value='low'))
            mocks['entry'] = stack.enter_context(patch.object(automatic,'enter_line_from_end_high',return_value='low'))
            finish = automatic._run_measurements('test', receiver, self.config, 'unused', self.data)
        return mocks, finish

    def test_sparse_selection_routes_around_obstacle_between_selected_points(self):
        self.config['points_selection'] = {'mode':'custom','point_ids':[2,9]}
        mocks, finish = self.run_mocked()
        self.assertEqual([call.args[6]['measurement_index'] for call in mocks['force'].call_args_list], [2,9])
        mocks['avoid'].assert_called_once()
        self.assertEqual(mocks['avoid'].call_args.kwargs['current_position'],100.)
        self.assertEqual(mocks['avoid'].call_args.kwargs['next_position'],800.)
        self.assertEqual(finish,'end')

    def test_starting_after_obstacle_uses_end_entry(self):
        self.config['points_selection'] = {'mode':'from_point','from_point':8}
        sys.path.insert(0,str(ROOT/'src/program/commands'))
        import run_measurement_sequence as sequence
        self.assertTrue(sequence.first_measurement_is_blocked(self.config,self.data))
        mocks, finish = self.run_mocked()
        mocks['entry'].assert_called_once()
        mocks['high_to_low'].assert_not_called()
        self.assertEqual([call.args[6]['measurement_index'] for call in mocks['force'].call_args_list],[8,9,10,11])
        self.assertEqual(finish,'end')

    def test_center_and_config_width_override_read_only_browser_values(self):
        fields = self.fields()
        fields.update({'obstacle.start':['0'], 'obstacle.end':['999'], 'obstacle_width':['10'],
                       'points_selection.mode':['custom'], 'points_selection.point_ids':['2,9']})
        result = edited_config(self.config, fields, self.data)
        self.assertEqual(result['obstacle_width'],200.)
        self.assertEqual(result['obstacle'],{'present':True,'width':200.,'position':450.,'start':350.,'end':550.})
        self.assertEqual(result['points_selection']['point_ids'],[2,9])

    def test_center_config_is_supported_for_cli(self):
        self.config['obstacle'] = {'position':400.}
        config = canonical_config(self.config)
        self.assertEqual(config['obstacle']['start'],300.)
        self.assertEqual(obstacle_interval(config),(300.,500.))
        self.assertNotIn('start',self.config['obstacle'])

    def test_invalid_obstacle_width_is_rejected(self):
        for width in (0,-1,True,float('inf')):
            self.config['obstacle_width'] = width
            with self.assertRaisesRegex(ValueError,'Obstacle width'):
                validate_measurement_config(self.config,self.data)

    def test_form_orders_selection_and_combines_timing_fields(self):
        page = form_html(self.config)
        self.assertLess(page.index('<legend>Obstacle'),page.index('<legend>Points selection'))
        self.assertLess(page.index('<legend>Points selection'),page.index('<legend>Force measurement'))
        self.assertIn('Settling / Hold time [s]</span><input',page)
        self.assertIn('id="obstacle-width" type="hidden" value="200.0" readonly',page)
        self.assertIn('id="points-selection-dialog"',page)
        self.assertIn('src="/static/point_selection.js"',page)
        self.assertNotIn('Target Force',page)
