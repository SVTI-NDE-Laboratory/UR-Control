"""The shared default URP path overrides profiles and stale browser snapshots."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import server, flexible_worker
from src.program.webapp2.settings import ROUTINE_FILE
import measurement_config
from line_planner import line_geometry
from read_routines import read_routines_file
from webapp.config_form import edited_config


class ProgramPathTests(unittest.TestCase):
    def setUp(self):
        self.config = server.legacy.load_default_config("point_to_point")
        self.data = read_routines_file(ROUTINE_FILE)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.default = Path(self.folder.name) / "config_default.json"
        for patcher in (patch.object(measurement_config, "DEFAULT_CONFIG_FILE", self.default),
                        patch.object(server.legacy, "SERVER_CONFIG_FILE", self.default)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.write_default("Inspection/Programs/Apply Force/first.urp")

    def write_default(self, path):
        config = deepcopy(self.config)
        config["measurement"]["program_path"] = path
        self.default.write_text(json.dumps(config))

    def test_automatic_profiles_read_the_current_shared_path(self):
        for path in ("Inspection/Programs/Apply Force/first.urp", "Custom/New Path/second.urp"):
            self.write_default(path)
            for profile in ("server", "timer"):
                config = server.legacy.load_default_config("point_to_point", profile)
                self.assertEqual(config["measurement"]["program_path"], path)

    def test_timer_and_feedback_share_defaults_and_preserve_saved_stop_method(self):
        defaults = server.legacy.get_configuration_defaults()
        self.assertEqual(set(defaults), {"server", "timer"})
        self.assertEqual(defaults["timer"]["measurement"]["stop_method"], "timer")
        self.assertEqual(defaults["server"]["measurement"]["stop_method"], "client_feedback")
        for mode in ("server", "timer"):
            self.assertEqual(server.legacy.default_config_path("point_to_point", mode), self.default)
            self.assertEqual(defaults[mode]["measurement"]["holding_force"], self.config["measurement"]["holding_force"])
        self.default.write_text(json.dumps(defaults["timer"]))
        self.assertEqual(server.legacy.load_default_config("point_to_point")["measurement"]["stop_method"], "timer")

    def test_flexible_commands_read_path_again_after_file_edit(self):
        flexible = flexible_worker.flexible
        for path in ("Custom/first.urp", "Custom/Second Folder/second.urp"):
            self.write_default(path)
            for args in (["3"], ["manual"]):
                settings, _ = flexible.force_measurement_settings(args)
                self.assertEqual(settings["program_path"], path)

    def test_stale_hidden_browser_path_cannot_override_current_defaults(self):
        fields = {}
        for section in ("line", "motion", "measurement"):
            for key, value in self.config[section].items():
                fields[f"{section}.{key}"] = [str(value).lower()]
        fields["line.x_end"] = [str(line_geometry(self.config, self.data)["x_end"])]
        fields["measurement.program_path"] = ["Old/browser-cached.urp"]
        defaults = server.legacy.load_default_config("point_to_point", "timer")
        saved = edited_config(defaults, fields, self.data)
        self.assertEqual(saved["measurement"]["program_path"], "Inspection/Programs/Apply Force/first.urp")

    def test_start_refreshes_path_in_an_older_validated_configuration(self):
        old = deepcopy(self.config)
        old["measurement"]["program_path"] = "Old/validated.urp"
        self.write_default("Updated/Runtime Program.urp")
        with patch.object(server.legacy, "state") as state, patch.object(server.legacy, "read_routines_file", return_value=self.data), patch.object(server.legacy, "assert_safe_start_position"):
            state.get_config.return_value = old
            state.get_routine_file.return_value = ROUTINE_FILE
            server.legacy.start_measurement(server.MeasurementStartRequest(output_directory=Path(self.folder.name)))
            launched = state.workers.start_measurement.call_args.args[0]
            self.assertEqual(launched["measurement"]["program_path"], "Updated/Runtime Program.urp")
