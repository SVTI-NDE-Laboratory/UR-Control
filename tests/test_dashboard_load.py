"""Dashboard load syntax retries never play an unconfirmed program."""

import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/robot"))
import robot_connection


class DashboardLoadTests(unittest.TestCase):
    def test_raw_path_success_preserves_existing_command(self):
        path = "/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp"
        with patch.object(robot_connection, "dashboard_command", side_effect=[f"Loading program: {path}", "Starting program"]) as command:
            robot_connection.load_and_play_urp("robot", path)
        self.assertEqual(command.call_args_list, [call("robot", f"load {path}"), call("robot", "play")])

    def test_parser_rejection_retries_quoted_path_before_play(self):
        path = "/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp"
        with patch.object(robot_connection, "dashboard_command", side_effect=["could not understand: load " + path, "Loading program: " + path, "Starting program"]) as command:
            robot_connection.load_and_play_urp("robot", path)
        self.assertEqual(command.call_args_list, [call("robot", f"load {path}"), call("robot", f'load "{path}"'), call("robot", "play")])

    def test_rejected_quote_reports_both_replies_and_never_plays(self):
        path = "Apply Force/apply_force.urp"
        with patch.object(robot_connection, "dashboard_command", side_effect=["could not understand: raw", "File not found: quoted"]) as command:
            with self.assertRaisesRegex(RuntimeError, "Unquoted path:.*Quoted path:"):
                robot_connection.load_and_play_urp("robot", path)
        self.assertEqual(command.call_count, 2)

    def test_file_missing_is_not_treated_as_a_parser_error(self):
        with patch.object(robot_connection, "dashboard_command", return_value="File not found: Apply Force/apply_force.urp") as command:
            with self.assertRaisesRegex(RuntimeError, "File not found"):
                robot_connection.load_and_play_urp("robot", "Apply Force/apply_force.urp")
        command.assert_called_once()

    def test_parser_error_without_whitespace_does_not_retry(self):
        with patch.object(robot_connection, "dashboard_command", return_value="could not understand: load force.urp") as command:
            with self.assertRaisesRegex(RuntimeError, "controller rejected"):
                robot_connection.load_and_play_urp("robot", "force.urp")
        command.assert_called_once()

    def test_invalid_path_is_rejected_before_contacting_controller(self):
        for path in ("", "  ", "force.urp\nplay", '"force.urp"', "force\x00.urp"):
            with self.subTest(path=path), patch.object(robot_connection, "dashboard_command") as command:
                with self.assertRaises(ValueError):
                    robot_connection.load_and_play_urp("robot", path)
                command.assert_not_called()
