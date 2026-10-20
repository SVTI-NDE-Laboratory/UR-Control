"""Flexible web/tool force commands select the unified program's stop mode."""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import flexible_worker as worker
from src.program.webapp2.settings import ROUTINE_FILE
from read_routines import read_routines_file

flexible = worker.flexible


class FlexibleStopMethodTests(unittest.TestCase):
    def test_numeric_durations_select_python_timer(self):
        for args in (["2.75"], ["160", "2.75"], ["140", "160", "2.75"]):
            with self.subTest(args=args):
                settings, callback = flexible.force_measurement_settings(args)
                self.assertEqual(settings["stop_method"], "timer")
                self.assertEqual(settings["hold_duration"], 2.75)
                self.assertIsNone(callback)
                self.assertEqual(settings["program_path"], flexible.read_default_program_path())

    def test_manual_hold_uses_feedback_until_operator_stop(self):
        settings, callback = flexible.force_measurement_settings(["manual"])
        self.assertEqual(settings["stop_method"], "client_feedback")
        self.assertIs(callback, flexible.manual_force_hold)

    def test_zero_duration_keeps_immediate_feedback_release(self):
        settings, callback = flexible.force_measurement_settings(["0"])
        self.assertEqual(settings["stop_method"], "client_feedback")
        self.assertTrue(callable(callback))
        self.assertGreater(settings["hold_duration"], 0)

    def test_invalid_durations_are_rejected(self):
        for value in ("-1", "nan", "inf"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                flexible.force_measurement_settings([value])

    def test_cli_passes_mode_duration_and_simulation_to_shared_force_interface(self):
        for command, feedback, duration in [("force 2.75", False, 2.75), ("force manual", True, 3)]:
            with self.subTest(command=command), patch("builtins.input", side_effect=[command, "end"]), patch.object(flexible, "write_state"), patch.object(flexible, "print_help"), patch.object(flexible, "apply_force", return_value=(True, "test")) as apply:
                flexible.run_interactive_loop(Mock(), {}, {}, Path("unused.json"), 100, 100, (0, 0))
                self.assertEqual(apply.call_args.kwargs["stop_method"], "client_feedback" if feedback else "timer")
                self.assertEqual(apply.call_args.kwargs["hold_duration"], duration)
                self.assertEqual(apply.call_args.args[5], flexible.SIMULATION)

    def test_webapp_passes_python_timer_duration_and_simulation(self):
        data = read_routines_file(ROUTINE_FILE)
        position = {"measurement_xy": {"X": 100, "Y": -20}}
        for simulation in (False, True):
            with self.subTest(simulation=simulation), patch.object(worker, "assert_in_plane", return_value=position), patch.object(flexible, "apply_force", return_value=(True, "test")) as apply:
                worker.perform_action({"action": "force", "threshold": 140, "force": 160, "duration": 2.75, "simulation": simulation}, Mock(), data, worker.plane_geometry(data), Path("unused.json"))
                self.assertEqual(apply.call_args.kwargs["stop_method"], "timer")
                self.assertEqual(apply.call_args.kwargs["hold_duration"], 2.75)
                self.assertIsNone(apply.call_args.kwargs["acquire_data"])
                self.assertEqual(apply.call_args.args[5], simulation)


if __name__ == "__main__":
    unittest.main()
