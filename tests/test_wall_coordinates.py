"""Wall offsets, upward-positive Y, limits and saved results agree without hardware."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.program.webapp2 import server, flexible_worker
from src.program.commands import run_flexible_measurement as flexible
from wall_coordinates import local_to_wall, wall_to_local, wall_limits, read_wall_coordinates
from line_planner import line_geometry, point_pose, is_obstacle, start_entry_crosses_obstacle
from measurement_config import canonical_config, configuration_file, validate_measurement_config
from measurement_plan import create_measurement_plan
from webapp.config_form import edited_config


class WallCoordinateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "wall_coordinates.json"
        self.reference = {"p_start_l": {"x": 1200.0, "y": -500.0},
                          "movement_limits": {"y_direction": "up", "y_max_distance": 400.0}}
        self.save_reference()
        environment = patch.dict(os.environ, {"UR15_WALL_COORDINATES": str(self.path)})
        environment.start()
        self.addCleanup(environment.stop)
        self.data = {"waypoints": {
            "p_start_l": {"p": [0, 0, 0, 0, 0, 0]},
            "p_end_l": {"p": [.6, .8, 0, 0, 0, 0]},
            "p_start_h": {"p": [0, 0, -.1, 0, 0, 0]},
        }, "routines": []}
        self.config = canonical_config(json.loads((ROOT / "src/program/config/config_default.json").read_text()))
        self.config["line"].update(x_start=1500.0, x_end=1700.0, offset_y=-300.0,
                                   spacing_source="count", number_of_measurements=3)

    def save_reference(self):
        self.path.write_text(json.dumps(self.reference), encoding="utf-8")

    def test_wall_pose_status_and_results_match_on_rotated_plane(self):
        geometry = line_geometry(self.config, self.data)
        target = flexible.measurement_pose(self.data, geometry, 1500, -300)
        # Wall delta (300, +200) becomes local delta (300, -200).
        for actual, expected in zip(target[:3], [.34, .12, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(wall_to_local(1500, -300), (300, -200))
        self.assertEqual(local_to_wall(300, -200), (1500, -300))
        status = flexible_worker.classify_plane(target, [], self.data)
        self.assertTrue(status["measurement_zone"])
        self.assertAlmostEqual(status["measurement_xy"]["X"], 1500)
        self.assertAlmostEqual(status["measurement_xy"]["Y"], -300)
        plan = create_measurement_plan(self.config, self.data)
        self.assertEqual(plan["wall_coordinates"], self.reference)
        self.assertEqual([point["plane_position_x"] for point in plan["points"]], [1500, 1600, 1700])
        self.assertEqual([point["plane_position_y"] for point in plan["points"]], [-300] * 3)
        self.assertEqual(point_pose(geometry, 0), target)

    def test_up_and_down_limits_follow_wall_y_for_both_modes(self):
        geometry = flexible_worker.plane_geometry(self.data)
        self.assertEqual(wall_limits(1000), (1200, 2200, -500, -100))
        flexible_worker.validate_target(1500, -100, geometry)
        self.config["line"]["offset_y"] = -100
        validate_measurement_config(self.config, self.data)

        for y in (-501, -99):
            with self.assertRaises(ValueError):
                flexible_worker.validate_target(1500, y, geometry)
            self.config["line"]["offset_y"] = y
            with self.assertRaises(ValueError):
                validate_measurement_config(self.config, self.data)
        self.reference["movement_limits"]["y_direction"] = "down"
        self.save_reference()
        self.assertEqual(wall_limits(1000), (1200, 2200, -900, -500))
        flexible_worker.validate_target(1500, -900, geometry)
        self.config["line"]["offset_y"] = -900
        validate_measurement_config(self.config, self.data)

    def test_positive_wall_y_moves_along_negative_local_y(self):
        self.reference["p_start_l"]["y"] = 0
        self.save_reference()
        geometry = flexible_worker.plane_geometry(self.data)
        target = flexible.measurement_pose(self.data, geometry, 1200, 200)
        self.assertEqual(wall_to_local(1200, 200), (0, -200))
        status = flexible_worker.classify_plane(target, [], self.data)
        self.assertTrue(status["measurement_zone"])
        self.assertAlmostEqual(status["measurement_xy"]["Y"], 200)

    def test_options_and_queued_move_use_offset_wall_coordinates(self):
        with patch.object(server, "read_routines_file", return_value=self.data):
            options = server.flexible_options_data()
            self.assertEqual((options["x_min"], options["x_max"]), (1200, 2200))
            self.assertEqual((options["y_min"], options["y_max"]), (-500, -100))
            request = server.FlexibleRequest(action="move", x=1500, y=-300)
        geometry = flexible_worker.plane_geometry(self.data)
        receiver = Mock()
        receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_start_l"]["p"]
        receiver.getSafetyStatusBits.return_value = 0
        with patch.object(flexible_worker, "assert_in_plane"), patch.object(flexible, "movel_pose") as move:
            flexible_worker.perform_action(request.model_dump(), receiver, self.data, geometry, Path("unused.json"))
        self.assertEqual(move.call_args.args[2], flexible.measurement_pose(self.data, geometry, 1500, -300))

    def test_obstacle_and_start_entry_use_wall_x(self):
        self.config["obstacle"].update(present=True, position=1600, width=100)
        geometry = validate_measurement_config(self.config, self.data)
        self.assertFalse(is_obstacle(0, self.config))
        self.assertTrue(is_obstacle(100, self.config))
        self.assertEqual([p["scheduled"] for p in create_measurement_plan(self.config, self.data)["points"]], [True, False, True])
        self.config["obstacle"].update(position=1350, width=100)
        self.assertTrue(start_entry_crosses_obstacle(self.config, geometry))

    def test_rtm_state_uses_live_wall_projection_and_matches_app_during_force(self):
        from src.program.commands import run_measurement_sequence as sequence
        from data_acquisition.server_state import protocol_state_response
        receiver = Mock()
        receiver.getActualTCPSpeed.return_value = [0.] * 6
        self.config["measurement"]["stop_method"] = "client_feedback"
        state_path = self.path.parent / "state.json"
        with patch.object(sequence, "AcquisitionControlServer") as factory, patch.object(sequence, "read_server_config", return_value={"host":"127.0.0.1", "port":0}):
            sequence.start_acquisition_if_enabled(self.config, state_path, 2, lambda: receiver, self.data)
            provider = factory.call_args.kwargs["state_provider"]
            geometry = line_geometry(self.config, self.data)
            for x, y, normal_travel in ((1500, -300, 0), (1600, -250, .03)):
                pose = flexible.measurement_pose(self.data, geometry, x, y)
                pose[2] += normal_travel
                receiver.getActualTCPPose.return_value = pose
                response = protocol_state_response({"ready":True, "context":{"measurement_index":2}, "state":provider()})
                self.assertAlmostEqual(response["X"], x)
                self.assertAlmostEqual(response["Y"], y)
                self.assertEqual(response["Point"], 2)
                self.assertFalse(response["Moving"])
                app_xy = flexible.pose_to_measurement_xy(pose, self.data, geometry)
                self.assertAlmostEqual(response["X"], app_xy[0])
                self.assertAlmostEqual(response["Y"], app_xy[1])

    def test_rtm_state_does_not_send_base_coordinates_when_wall_position_is_unknown(self):
        from src.program.commands import run_measurement_sequence as sequence
        from data_acquisition.server_state import protocol_state_response
        state_path = self.path.parent / "state.json"
        state_path.write_text(json.dumps({"tcp_position":{"X":999, "Y":888}}))
        plane = {"start_pose":[0.] * 6, "x_axis":[1, 0, 0], "y_axis":[0, 1, 0]}
        response = protocol_state_response({"state":sequence.read_live_state_snapshot(state_path, None, wall_plane=plane)})
        self.assertEqual(response["X"], -9999)
        self.assertIsNone(response["Y"])
        receiver = Mock()
        receiver.getActualTCPPose.side_effect = RuntimeError("RTDE unavailable")
        response = protocol_state_response({"state":sequence.read_live_state_snapshot(state_path, receiver, wall_plane=plane)})
        self.assertEqual(response["X"], -9999)
        self.assertEqual(response["Error"], "RTDE unavailable")

    def test_legacy_configuration_converts_once_and_keeps_physical_positions(self):
        legacy = json.loads((ROOT / "src/program/config/config_default.json").read_text())
        legacy["line"].update(x_start=100, x_end=500, offset_y=-220)
        legacy["obstacle"].update(position=300)
        converted = canonical_config(legacy)
        self.assertEqual(converted["line"]["x_start"], 1300)
        self.assertEqual(converted["line"]["x_end"], 1700)
        self.assertEqual(converted["line"]["offset_y"], -280)
        self.assertEqual(converted["obstacle"]["position"], 1500)
        stored = configuration_file(converted)
        self.assertEqual(canonical_config(stored), converted)
        self.assertEqual(list(stored)[:5], ["line", "obstacle", "points_selections", "force", "motion"])

    def test_zero_wall_x_is_a_position_and_legacy_full_span_is_preserved(self):
        self.reference["p_start_l"]["x"] = -500
        self.save_reference()
        self.config["line"].update(x_start=-500, x_end=0)
        self.assertEqual(line_geometry(self.config, self.data)["length"], 500)
        legacy = json.loads((ROOT / "src/program/config/config_default.json").read_text())
        self.assertEqual(line_geometry(canonical_config(legacy), self.data)["length"], 1000)

    def test_form_does_not_convert_wall_inputs_twice(self):
        fields = {}
        for section in ("line", "motion", "measurement"):
            for key, value in self.config[section].items():
                fields[f"{section}.{key}"] = [str(value).lower()]
        submitted = edited_config(self.config, fields, self.data)
        restored = canonical_config(configuration_file(submitted))
        self.assertEqual(restored["line"]["x_start"], 1500)
        self.assertEqual(restored["line"]["x_end"], 1700)
        self.assertEqual(restored["line"]["offset_y"], -300)

    def test_entry_exit_return_to_taught_poses_with_nonzero_wall_origin(self):
        geometry = flexible_worker.plane_geometry(self.data)
        with patch.object(flexible, "ENTRY_SIDE", "start"), patch.object(flexible, "run_routine"), patch.object(flexible, "movel_pose") as move:
            self.assertEqual(flexible.run_entry_sequence(Mock(), self.data, geometry, .1, .1), (1200, -500))
            self.assertEqual(move.call_args.args[2], self.data["waypoints"]["p_start_l"]["p"])
            flexible.run_exit_sequence(Mock(), self.data, geometry, .1, .1)
            self.assertEqual(move.call_args.args[2], self.data["waypoints"]["p_start_h"]["p"])

    def test_invalid_reference_is_rejected(self):
        for direction, distance in (("left", 400), ("up", -1), ("down", float("nan")), ("up", True)):
            self.reference["movement_limits"].update(y_direction=direction, y_max_distance=distance)
            self.save_reference()
            with self.assertRaises(ValueError):
                read_wall_coordinates(self.path)
