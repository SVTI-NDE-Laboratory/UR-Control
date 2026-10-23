"""Hardware-free regression checks for independent spacing and simulation."""

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import server, flexible_worker as worker
from src.program.webapp2.settings import ROUTINE_FILE
from webapp.config_form import edited_config
from line_planner import line_geometry
from measurement_plan import create_measurement_plan
from read_routines import read_routines_file


class FitTests(unittest.TestCase):
    def setUp(self):
        self.data = read_routines_file(ROUTINE_FILE)
        self.defaults = server.legacy.load_default_config("point_to_point", "server")
        self.config = deepcopy(self.defaults)
        self.config.pop("obstacle", None)
        self.config["line"].update(
            auto_fit=False, x_start=23.5, x_end=1, increment=12.25,
            number_of_measurements=7, offset_y=-20,
        )

    def fields(self):
        result = {"line.method": ["point_to_point"]}
        for key, value in self.config["line"].items():
            result[f"line.{key}"] = [str(value).lower()]
        for section, values in self.config.items():
            if section not in {"motion", "measurement"}:
                continue
            for key, value in values.items():
                text = ", ".join(map(str, value)) if isinstance(value, list) else str(value).lower()
                result[f"{section}.{key}"] = [text]
        return result

    def test_independent_spacing_ignores_end_and_spacing_source(self):
        for source in ("increment", "count"):
            self.config["line"]["spacing_source"] = source
            config = edited_config(self.defaults, self.fields(), self.data)
            parameters = config["line"]
            self.assertEqual(parameters["x_start"], 23.5)
            self.assertEqual(parameters["x_end"], 97)
            self.assertEqual(parameters["increment"], 12.25)
            self.assertEqual(parameters["number_of_measurements"], 7)
            plan = create_measurement_plan(config, self.data)
            self.assertEqual([p["line_position"] for p in plan["points"]],
                             [i * 12.25 for i in range(7)])

    def test_independent_start_change_preserves_spacing_and_count(self):
        self.config["line"]["x_start"] = 50
        geometry = line_geometry(self.config, self.data)
        self.assertEqual((geometry["x_end"], geometry["increment"], geometry["number_of_measurements"]),
                         (123.5, 12.25, 7))

    def test_independent_end_cannot_exceed_taught_range(self):
        self.config["line"]["increment"] = 100000
        with self.assertRaisesRegex(ValueError, "taught"):
            edited_config(self.defaults, self.fields(), self.data)

    def test_auto_fit_still_derives_spacing_or_count(self):
        parameters = self.config["line"]
        parameters.update(auto_fit=True, x_start=0, x_end=100, increment=30,
                          number_of_measurements=6, spacing_source="increment")
        geometry = line_geometry(self.config, self.data)
        self.assertEqual((geometry["number_of_measurements"], geometry["increment"]), (4, 30))
        parameters["spacing_source"] = "count"
        geometry = line_geometry(self.config, self.data)
        self.assertEqual((geometry["number_of_measurements"], geometry["increment"]), (6, 20))

    def test_automatic_simulation_preserves_positive_forces(self):
        fields = self.fields()
        fields.update({"measurement.simulation": ["true"],
                       "measurement.target_force": ["160"], "measurement.settling_time": ["1.5"]})
        config = edited_config(self.defaults, fields, self.data)
        self.assertTrue(config["measurement"]["simulation"])
        self.assertEqual(config["measurement"]["target_force"], 160)
        fields["measurement.simulation"] = ["false"]
        self.assertFalse(edited_config(self.defaults, fields, self.data)["measurement"]["simulation"])

    def test_flexible_simulation_reaches_force_program(self):
        action = server.FlexibleRequest(action="force", simulation=True, duration=0).model_dump()
        position = {"measurement_xy": {"X": 0, "Y": 0}}
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "assert_in_plane", return_value=position), patch.object(worker.flexible, "apply_force", return_value=(True, "test")) as apply:
            worker.perform_action(action, Mock(), self.data, worker.plane_geometry(self.data), Path(directory) / "state.json")
        self.assertEqual(apply.call_args.args[3:5], (200, True))


if __name__ == "__main__":
    unittest.main()
