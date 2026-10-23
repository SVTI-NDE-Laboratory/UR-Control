"""The flat config schema preserves planning, obstacles, and force stop modes."""

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import server
from src.program.webapp2.settings import ROUTINE_FILE
from measurement_config import canonical_config, configuration_file, read_measurement_config, validate_measurement_config, measurement_stop_method
from measurement_plan import create_measurement_plan
from line_planner import line_geometry, crosses_obstacle
from read_routines import read_routines_file
from webapp.config_form import edited_config, form_html


class ConfigSchemaTests(unittest.TestCase):
    def setUp(self):
        self.data = read_routines_file(ROUTINE_FILE)
        self.config = server.legacy.load_default_config("point_to_point")

    def fields(self):
        result = {}
        for section in ("line", "motion", "measurement"):
            for key, value in self.config[section].items():
                result[f"{section}.{key}"] = [str(value).lower()]
        result["line.x_end"] = [str(line_geometry(self.config, self.data)["x_end"])]
        return result

    def test_default_file_uses_only_new_schema_and_is_valid(self):
        path = ROOT / "src/program/config/config_default.json"
        raw = json.loads(path.read_text())
        self.assertNotIn("method", raw["line"])
        self.assertNotIn("parameters", raw["line"])
        self.assertNotIn("data_server", raw["force"])
        self.assertEqual(list(raw), ["line", "obstacle", "points_selections", "force", "motion"])
        self.assertIn("steps", raw["line"])
        self.assertIn("nb_points", raw["line"])
        loaded = read_measurement_config(path, routines_data=self.data)
        self.assertEqual(loaded["measurement"]["stop_method"], "client_feedback")
        self.assertGreater(len(create_measurement_plan(loaded, self.data)["points"]), 1)

    def test_ordered_schema_round_trip_preserves_plan_and_force(self):
        self.config["obstacle"] = {"present": True, "width": 200., "position": 400.}
        self.config["points_selection"] = {"mode": "custom", "point_ids": [2, 7]}
        stored = configuration_file(self.config)
        self.assertEqual(list(stored), ["line", "obstacle", "points_selections", "force", "motion"])
        self.assertEqual(stored["obstacle"], {"present": True, "width": 200., "position": 400., "start": 300., "end": 500.})
        self.assertNotIn("measurement", stored)
        self.assertNotIn("increment", stored["line"])
        self.assertEqual(configuration_file(stored), stored)
        restored = canonical_config(stored)
        self.assertEqual(restored["measurement"], self.config["measurement"])
        self.assertEqual(create_measurement_plan(restored, self.data)["points"],
                         create_measurement_plan(self.config, self.data)["points"])

    def test_disabled_obstacle_retains_center_width_and_bounds(self):
        fields = self.fields()
        fields["obstacle.position"] = ["650"]
        saved = edited_config(self.config, fields, self.data)
        stored = configuration_file(saved)
        self.assertEqual(stored["obstacle"], {"present": False, "width": 200., "position": 650., "start": 550., "end": 750.})
        self.assertTrue(all(point["scheduled"] for point in create_measurement_plan(saved, self.data)["points"]))
        fields["obstacle.enabled"] = ["true"]
        enabled = edited_config(canonical_config(stored), fields, self.data)
        self.assertTrue(enabled["obstacle"]["present"])
        self.assertEqual(enabled["obstacle"]["position"], 650.)

    def test_explicit_interval_migration_preserves_its_width(self):
        self.config["obstacle"] = {"start": 300., "end": 650.}
        stored = configuration_file(self.config)
        self.assertEqual(stored["obstacle"], {"present": True, "width": 350., "position": 475., "start": 300., "end": 650.})
        self.assertEqual(configuration_file(stored), stored)

    def test_legacy_point_config_is_converted_without_changing_the_plan(self):
        old = deepcopy(self.config)
        old["line"] = {"method": "point_to_point", "parameters": old["line"]}
        old["measurement"].pop("stop_method")
        old["measurement"]["data_server"] = False
        new = canonical_config(old)
        self.assertEqual(new["measurement"]["stop_method"], "timer")
        self.assertNotIn("data_server", new["measurement"])
        self.assertEqual(create_measurement_plan(old, self.data)["points"],
                         create_measurement_plan(new, self.data)["points"])
        self.assertIn("parameters", old["line"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.json"
            path.write_text(json.dumps(old))
            self.assertEqual(read_measurement_config(path, routines_data=self.data), new)

    def test_only_time_and_feedback_are_valid_stop_methods(self):
        for method in ("timer", "client_feedback"):
            self.config["measurement"]["stop_method"] = method
            validate_measurement_config(self.config, self.data)
            self.assertEqual(measurement_stop_method(self.config), method)
        for method in (True, False, None, "server", "mira", "", "Time"):
            with self.subTest(method=method):
                self.config["measurement"]["stop_method"] = method
                with self.assertRaisesRegex(ValueError, "stop_method"):
                    validate_measurement_config(self.config, self.data)

    def test_legacy_stop_boolean_maps_to_corresponding_mode(self):
        for old_value, expected in [(False, "timer"), (True, "client_feedback")]:
            old = deepcopy(self.config)
            old["measurement"].pop("stop_method")
            old["measurement"]["data_server"] = old_value
            self.assertEqual(canonical_config(old)["measurement"]["stop_method"], expected)

    def test_hold_duration_is_configurable_and_must_be_positive_finite(self):
        fields = self.fields()
        fields["measurement.stop_method"] = ["timer"]
        fields["measurement.hold_duration"] = ["2.75"]
        self.assertEqual(edited_config(self.config, fields, self.data)["measurement"]["hold_duration"], 2.75)
        for value in (0, -1, True, "5", float("nan"), float("inf")):
            self.config["measurement"]["hold_duration"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "hold_duration"):
                validate_measurement_config(self.config, self.data)

    def test_form_saves_flat_line_and_selected_stop_method(self):
        for method in ("timer", "client_feedback"):
            fields = self.fields()
            fields["measurement.stop_method"] = [method]
            saved = edited_config(self.config, fields, self.data)
            self.assertEqual(saved["measurement"]["stop_method"], method)
            self.assertNotIn("data_server", saved["measurement"])
            self.assertNotIn("parameters", saved["line"])
            self.assertNotIn("method", saved["line"])
        html = form_html(self.config)
        self.assertIn('name="line.increment"', html)
        self.assertIn('name="measurement.stop_method"', html)
        self.assertNotIn('name="line.method"', html)
        self.assertNotIn('name="line.parameters.', html)

    def test_flat_schema_obstacle_skips_points_without_changing_grid(self):
        self.config["line"].update(x_start=100, x_end=1000, increment=100, spacing_source="increment")
        before = create_measurement_plan(self.config, self.data)["points"]
        self.config["obstacle"] = {"start": 300, "end": 500}
        validate_measurement_config(self.config, self.data)
        after = create_measurement_plan(self.config, self.data)["points"]
        self.assertEqual([p["plane_position_x"] for p in before], [p["plane_position_x"] for p in after])
        self.assertEqual([p["tcp_pose"] for p in before], [p["tcp_pose"] for p in after])
        self.assertEqual([p["plane_position_x"] for p in after if not p["scheduled"]], [300, 400, 500])
        self.assertTrue(crosses_obstacle(100, 500, self.config))

    def test_time_mode_disables_external_listener_before_connecting(self):
        sys.path.insert(0, str(ROOT / "src/program/commands"))
        import run_measurement_sequence as sequence
        self.config["measurement"]["stop_method"] = "timer"
        with patch.object(sequence, "AcquisitionControlServer") as listener:
            self.assertEqual(sequence.start_acquisition_if_enabled(self.config, Path("unused.json")), (None, None))
            listener.assert_not_called()


if __name__ == "__main__":
    unittest.main()
