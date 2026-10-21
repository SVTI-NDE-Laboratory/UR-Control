"""Examples of the specified point discretization and absolute obstacle frame."""

import math
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import server
from line_planner import line_geometry, line_scope_warning, point_pose, is_obstacle, crosses_obstacle, start_entry_crosses_obstacle
from measurement_config import validate_measurement_config, canonical_config
from measurement_plan import create_measurement_plan
from webapp.config_form import edited_config, display_field_value, form_html


class MeasurementPositionTests(unittest.TestCase):
    def setUp(self):
        self.data = {"waypoints": {
            "p_start_l": {"p": [0, 0, 0, 0, 0, 0]},
            "p_end_l": {"p": [1, 0, 0, 0, 0, 0]},
            "p_start_h": {"p": [0, 0, -.1, 0, 0, 0]},
        }}
        self.config = {
            "line": {"method": "point_to_point", "parameters": {
                "start_point": "p_start_l", "end_point": "p_end_l",
                "x_start": 0., "x_end": 1000., "offset_y": 0.,
                "auto_fit": True, "increment": 100., "number_of_measurements": 11,
                "spacing_source": "increment",
            }},
            "motion": {"type": "l", "speed": 50., "acceleration": 100.},
            "measurement": {"program_path": "test.urp", "contact_threshold": 140.,
                            "holding_force": 160., "max_displacement": 10.,
                            "simulation": False, "stop_method": "timer"},
        }
        self.config = canonical_config(self.config)
        self.parameters = self.config["line"]

    def plan(self):
        validate_measurement_config(self.config, self.data)
        return create_measurement_plan(self.config, self.data)["points"]

    def test_increment_lead_keeps_increment_and_stays_below_end(self):
        self.parameters.update(x_start=100., x_end=975., increment=250., number_of_measurements=99)
        points = self.plan()
        self.assertEqual([p["x_coordinate"] for p in points], [100, 350, 600, 850])
        self.assertEqual(self.parameters["x_end"], 975)

    def test_count_lead_includes_both_ends(self):
        self.parameters.update(spacing_source="count", number_of_measurements=11, increment=123.)
        self.assertEqual(line_geometry(self.config, self.data)["increment"], 100)
        self.assertEqual([p["x_coordinate"] for p in self.plan()], list(range(0, 1001, 100)))

    def test_nonzero_start_and_y_offset_do_not_change_discretization(self):
        self.parameters.update(x_start=200., x_end=1000., spacing_source="count", number_of_measurements=5)
        unshifted = self.plan()
        self.parameters["offset_y"] = -37.5
        shifted = self.plan()
        self.assertEqual([p["x_coordinate"] for p in shifted], [200, 400, 600, 800, 1000])
        for before, after in zip(unshifted, shifted):
            self.assertEqual(before["x_coordinate"], after["x_coordinate"])
            self.assertEqual(after["y_coordinate"], -37.5)
            self.assertEqual(after["tcp_pose"][:3], [after["x_coordinate"], -37.5, 0])

    def test_independent_mode_calculates_end_without_changing_inputs(self):
        self.parameters.update(auto_fit=False, x_start=150., x_end=999., increment=80., number_of_measurements=6)
        self.assertEqual(line_geometry(self.config, self.data)["x_end"], 550)
        self.assertEqual([p["x_coordinate"] for p in self.plan()], [150, 230, 310, 390, 470, 550])
        self.assertEqual((self.parameters["increment"], self.parameters["number_of_measurements"]), (80, 6))

    def test_y_offset_remains_perpendicular_on_a_rotated_taught_line(self):
        self.data["waypoints"]["p_end_l"]["p"][:3] = [.6, .8, 0]
        self.parameters.update(x_start=200., x_end=800., offset_y=-37.5)
        for point in self.plan():
            x, y, z = point["tcp_pose"][:3]
            self.assertAlmostEqual(.6 * x + .8 * y, point["x_coordinate"])
            self.assertAlmostEqual(-.8 * x + .6 * y, -37.5)

    def test_independent_end_is_checked_against_taught_length(self):
        self.parameters.update(auto_fit=False, x_start=600., increment=150., number_of_measurements=5)
        with self.assertRaisesRegex(ValueError, "taught"):
            self.plan()

    def test_extended_endpoints_are_included_in_coordinates(self):
        self.parameters.update(x_start=-100., x_end=1100., increment=100.)
        points = self.plan()
        self.assertEqual([p["x_coordinate"] for p in points], list(range(-100, 1101, 100)))
        self.assertEqual(points[0]["tcp_pose"][:3], [-100., 0., 0.])
        self.assertEqual(points[-1]["tcp_pose"][:3], [1100., 0., 0.])
        self.assertIsNotNone(line_scope_warning(line_geometry(self.config, self.data)))

    def test_each_endpoint_cannot_exceed_100_mm_allowance(self):
        for start, end in [(-100.001, 1000.), (0., 1100.001),
                           (-101., -100.5), (1100.1, 1100.2)]:
            with self.subTest(start=start, end=end):
                self.parameters.update(x_start=start, x_end=end)
                with self.assertRaisesRegex(ValueError, "100 mm beyond"):
                    self.plan()

    def test_scope_warning_covers_either_end_and_computed_end(self):
        for start, end, warn in [(0., 1000., False), (100., 900., False),
                                 (-1., 900., True), (0., 1001., True)]:
            with self.subTest(start=start, end=end):
                self.parameters.update(x_start=start, x_end=end)
                self.assertEqual(bool(line_scope_warning(line_geometry(self.config, self.data))), warn)
        self.parameters.update(auto_fit=False, x_start=600., increment=150., number_of_measurements=4)
        geometry = line_geometry(self.config, self.data)
        self.assertEqual(geometry["x_end"], 1050.)
        self.assertIn("1050 mm", line_scope_warning(geometry))
        self.assertEqual(self.plan()[-1]["x_coordinate"], 1050.)

    def test_unconfirmed_extended_start_is_rejected_before_robot_or_worker(self):
        self.parameters.update(x_start=-50.)
        request = server.legacy.MeasurementStartRequest(output_directory=ROOT)
        with patch.object(server.legacy, "state") as state, patch.object(server.legacy, "read_routines_file", return_value=self.data), patch.object(server.legacy, "assert_safe_start_position") as robot:
            state.get_config.return_value = self.config
            state.get_routine_file.return_value = ROOT / "test-routines.json"
            with self.assertRaises(server.HTTPException) as error:
                server.legacy.start_measurement(request)
            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("outside the taught range", error.exception.detail)
            robot.assert_not_called()
            state.workers.start_measurement.assert_not_called()

    def test_confirmed_extended_and_unconfirmed_normal_start_can_launch(self):
        for start, confirmed in [(-50., True), (0., False)]:
            with self.subTest(start=start), tempfile.TemporaryDirectory() as folder:
                self.parameters["x_start"] = start
                request = server.legacy.MeasurementStartRequest(output_directory=Path(folder), outside_line_confirmed=confirmed)
                with patch.object(server.legacy, "state") as state, patch.object(server.legacy, "read_routines_file", return_value=self.data), patch.object(server.legacy, "assert_safe_start_position") as robot:
                    state.get_config.return_value = self.config
                    state.get_routine_file.return_value = ROOT / "test-routines.json"
                    result = server.legacy.start_measurement(request)
                    self.assertTrue(result["started"])
                    robot.assert_called_once()
                    state.workers.start_measurement.assert_called_once()

    def test_obstacle_uses_absolute_x_and_only_removes_measurements(self):
        self.parameters.update(x_start=200., x_end=900.)
        before = self.plan()
        geometry = line_geometry(self.config, self.data)
        self.config["obstacle"] = {"start": 300., "end": 600.}
        after = self.plan()
        self.assertEqual([p["x_coordinate"] for p in before], [p["x_coordinate"] for p in after])
        self.assertEqual([p["tcp_pose"] for p in before], [p["tcp_pose"] for p in after])
        self.assertEqual(line_geometry(self.config, self.data), geometry)
        self.assertEqual([p["x_coordinate"] for p in after if not p["measured"]], [300, 400, 500, 600])
        self.assertTrue(is_obstacle(100, self.config))  # distance 100 from X Start is X=300
        self.assertFalse(is_obstacle(0, self.config))
        self.assertTrue(crosses_obstacle(0, 500, self.config))

    def test_obstacle_can_overlap_or_be_outside_selected_section(self):
        self.parameters.update(x_start=200., x_end=600.)
        for start, end, skipped in [(100., 300., [200, 300]), (500., 800., [500, 600]), (850., 950., [])]:
            self.config["obstacle"] = {"start": start, "end": end}
            self.assertEqual([p["x_coordinate"] for p in self.plan() if not p["measured"]], skipped)

    def test_obstacle_before_selected_section_uses_end_entry_without_changing_points(self):
        import run_measurements as automatic
        sys.path.insert(0, str(ROOT / "src/program/commands"))
        import run_measurement_sequence as sequence
        self.parameters.update(auto_fit=False, x_start=200., number_of_measurements=1)
        self.config["obstacle"] = {"start": 100., "end": 150.}
        self.data["waypoints"]["p_end_h"] = {"p": [1, 0, -.1, 0, 0, 0]}
        self.assertTrue(self.plan()[0]["measured"])
        self.assertTrue(start_entry_crosses_obstacle(self.config, line_geometry(self.config, self.data)))
        self.assertTrue(sequence.first_measurement_is_blocked(self.config, self.data))
        receiver = Mock()
        receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_end_h"]["p"]
        with patch.object(automatic, "enter_line_from_end_high", return_value="low") as entry, patch.object(automatic, "high_to_low") as wrong_side, patch.object(automatic, "ensure_at_tcp_target"), patch.object(automatic, "apply_force", return_value=(True, "test")), patch.object(automatic, "write_state"), patch.object(automatic, "movel_pose"), patch.object(automatic, "translate_along_line"):
            finish = automatic._run_measurements("test", receiver, self.config, "unused-state.json", self.data)
        entry.assert_called_once()
        wrong_side.assert_not_called()
        self.assertEqual(finish, "end")

    def test_increment_larger_than_section_yields_only_first_point(self):
        self.parameters.update(x_start=200., x_end=900., increment=2000.)
        self.assertEqual([p["x_coordinate"] for p in self.plan()], [200])

    def test_single_independent_point_at_zero_has_zero_computed_end(self):
        self.parameters.update(auto_fit=False, number_of_measurements=1)
        geometry = line_geometry(self.config, self.data)
        self.assertEqual(geometry["x_end"], 0)
        self.assertEqual([p["x_coordinate"] for p in self.plan()], [0])
        self.assertEqual(point_pose(geometry, 100)[:3], [.1, 0, 0])

    def test_decimal_step_keeps_last_point_at_end(self):
        self.parameters.update(x_start=100., x_end=101., increment=.1)
        points = self.plan()
        self.assertEqual(len(points), 11)
        self.assertEqual(points[-1]["x_coordinate"], 101)

    def test_nonfinite_geometry_and_obstacles_are_rejected(self):
        for key in ("x_start", "x_end", "offset_y", "increment"):
            original = self.parameters[key]
            self.parameters[key] = math.nan
            with self.assertRaises(ValueError):
                self.plan()
            self.parameters[key] = original
        self.config["obstacle"] = {"start": 10, "end": math.inf}
        with self.assertRaisesRegex(ValueError, "finite"):
            self.plan()

    def test_decimal_fields_are_not_constrained_by_integer_defaults(self):
        defaults = deepcopy(self.config)
        defaults["line"].update(increment=100, x_start=0, x_end=1000, offset_y=0)
        fields = {"line.method": ["point_to_point"]}
        for key, value in defaults["line"].items():
            fields[f"line.{key}"] = [str(value).lower()]
        for section in ("motion", "measurement"):
            for key, value in defaults[section].items():
                fields[f"{section}.{key}"] = [str(value).lower()]
        fields.update({"line.increment": ["12.3456789"],
                       "line.x_start": ["20.25"], "line.offset_y": ["-2.75"]})
        config = edited_config(defaults, fields, self.data)
        self.assertEqual(config["line"]["increment"], 12.3456789)
        self.assertEqual(config["line"]["x_start"], 20.25)
        self.assertEqual(display_field_value("increment", 12.3456789), "12.35")

    def test_numeric_display_uses_at_most_two_decimals_without_trailing_zeros(self):
        for value, expected in [(100., "100"), (12.5, "12.5"), (12.3456789, "12.35"),
                                (0., "0"), (-0.001, "0"), (-2.755, "-2.75")]:
            with self.subTest(value=value):
                self.assertEqual(display_field_value("increment", value), expected)
        self.parameters["increment"] = 12.3456789
        page = form_html(self.config)
        self.assertIn('value="12.35"', page)
        self.assertIn('data-raw-value="12.3456789" data-display-value="12.35"', page)
        self.assertEqual(self.parameters["increment"], 12.3456789)


if __name__ == "__main__":
    unittest.main()
