"""Saved runs load as editable parameters without changing Results or defaults."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.program.webapp2 import server
from src.program.webapp2.saved_configuration import configuration_folders, read_saved_configuration
from measurement_config import configuration_file
from webapp.config_form import edited_config
from fastapi import HTTPException


class SavedConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.results = Path(self.temp.name)/'results'
        self.folder = self.results/'series'/'run_01'
        self.folder.mkdir(parents=True)
        (self.results/'empty').mkdir()
        self.routines = {'waypoints': {
            'p_start_l': {'p':[0,0,0,0,0,0]}, 'p_end_l': {'p':[1,0,0,0,0,0]},
            'p_start_h': {'p':[0,0,-.1,0,0,0]}, 'p_end_h': {'p':[1,0,-.1,0,0,0]},
        }}
        self.config = server.legacy.load_default_config('point_to_point')
        self.config['line'].update(x_start=100.,x_end=600.,offset_y=-125.,spacing_source='count',
                                   number_of_measurements=5,increment=125.,auto_fit=True)
        self.config['measurement'].update(target_force=240.,settling_time=2.5,hold_duration=2.,
                                          simulation=True,max_displacement=30.,stop_method='timer')
        self.config['motion'].update(speed=33.,acceleration=88.)
        self.config['obstacle']={'present':False,'width':80.,'position':300.}
        self.config['points_selection']={'mode':'custom','point_ids':[2,4]}
        self.path=self.folder/'measurement_configuration.json'
        self.path.write_text(json.dumps(configuration_file(self.config)),encoding='utf-8')
        self.original=self.path.read_bytes()
        self.old_config=server.legacy.state.get_config()
        self.old_defaults=server.legacy.state.get_loaded_defaults()
        self.addCleanup(server.legacy.state.set_config,self.old_config)
        self.addCleanup(server.legacy.state.set_loaded_defaults,self.old_defaults)
        self.defaults_file=server.PROFILE.paths['measurement_defaults']
        self.defaults_bytes=self.defaults_file.read_bytes()

    def test_browse_nested_folders_and_reject_escape(self):
        root=configuration_folders(self.results)
        self.assertEqual([folder['name'] for folder in root['folders']],['empty','series'])
        nested=configuration_folders(self.results,'series')
        self.assertTrue(nested['folders'][0]['has_configuration'])
        self.assertTrue(configuration_folders(self.results,'series/run_01')['can_load'])
        for directory in ('../',str(Path(self.temp.name).resolve())):
            with self.assertRaises(ValueError): configuration_folders(self.results,directory)
            with self.assertRaises(ValueError): read_saved_configuration(self.results,directory,self.routines)

    def test_read_saved_parameters_leaves_source_and_defaults_unchanged(self):
        config=read_saved_configuration(self.results,'series/run_01',self.routines)
        self.assertEqual(config['line']['spacing_source'],'count')
        self.assertEqual(config['measurement']['target_force'],240.)
        self.assertEqual(config['obstacle']['width'],80.)
        self.assertEqual(config['points_selection']['point_ids'],[2,4])
        self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual(self.defaults_file.read_bytes(),self.defaults_bytes)

    def test_older_configuration_filename_is_still_listed_and_loadable(self):
        legacy = self.path.with_name('config_used.json')
        self.path.rename(legacy)
        self.assertTrue(configuration_folders(self.results,'series/run_01')['can_load'])
        self.assertTrue(configuration_folders(self.results,'series')['folders'][0]['has_configuration'])
        config = read_saved_configuration(self.results,'series/run_01',self.routines)
        self.assertEqual(config['measurement']['target_force'],240.)
        self.assertEqual(legacy.read_bytes(),self.original)
        self.assertFalse(self.path.exists())

    def test_current_configuration_takes_precedence_over_legacy_file(self):
        legacy = self.path.with_name('config_used.json')
        legacy.write_text('{invalid',encoding='utf-8')
        config = read_saved_configuration(self.results,'series/run_01',self.routines)
        self.assertEqual(config['measurement']['target_force'],240.)

    def load(self):
        with patch.dict(server.PROFILE.paths,results_directory=self.results), patch.object(server,'read_routines_file',return_value=self.routines), patch.object(server.workers,'snapshot',return_value={'running':False}), patch.object(server.legacy,'TEMP_CONFIG_FILE',Path(self.temp.name)/'config_tmp.json'):
            return server.load_saved_configuration(server.SavedConfigurationSelection(directory='series/run_01'))

    def test_load_refresh_and_validate_retain_every_visible_parameter(self):
        self.assertTrue(self.load()['loaded'])
        page=server.configuration()
        self.assertIn('data-preserve-line="true"',page)
        self.assertIn('id="obstacle-width" type="hidden" value="80.0"',page)
        loaded=server.legacy.state.get_config()
        fields={f'{section}.{key}':[str(value).lower()] for section in ('line','motion','measurement')
                for key,value in loaded[section].items()}
        fields.update({'obstacle.position':['300'],'line.auto_fit':['true'],
                       'points_selection.mode':['custom'],'points_selection.point_ids':['2,4']})
        edited=edited_config(server.legacy.form_defaults('point_to_point'),fields,self.routines)
        for section in ('line','measurement','motion','obstacle'):
            self.assertEqual(edited[section],loaded[section])
        self.assertEqual(self.defaults_file.read_bytes(),self.defaults_bytes)
        server.legacy.reset_configuration()
        self.assertIsNone(server.legacy.state.get_loaded_defaults())

    def test_blocked_or_invalid_load_keeps_current_configuration(self):
        server.legacy.state.set_config(self.config)
        with patch.object(server.workers,'snapshot',return_value={'running':True}), patch.object(server.legacy,'write_json_atomic') as write:
            with self.assertRaises(HTTPException) as failure:
                server.load_saved_configuration(server.SavedConfigurationSelection(directory='series/run_01'))
            self.assertEqual(failure.exception.status_code,409)
            write.assert_not_called()
        self.path.write_text('{invalid',encoding='utf-8')
        with patch.dict(server.PROFILE.paths,results_directory=self.results), patch.object(server,'read_routines_file',return_value=self.routines), patch.object(server.workers,'snapshot',return_value={'running':False}):
            with self.assertRaises(HTTPException):
                server.load_saved_configuration(server.SavedConfigurationSelection(directory='series/run_01'))
        self.assertEqual(server.legacy.state.get_config(),self.config)

    def test_full_span_defaults_are_expanded_for_the_form(self):
        self.config['line'].update(x_start=0.,x_end=0.,spacing_source='increment',increment=200.)
        self.config['points_selection']={'mode':'all'}
        self.path.write_text(json.dumps(configuration_file(self.config)),encoding='utf-8')
        config=read_saved_configuration(self.results,'series/run_01',self.routines)
        self.assertEqual(config['line']['x_end'],1000.)
        self.assertEqual(config['line']['number_of_measurements'],6)
