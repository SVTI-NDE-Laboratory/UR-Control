"""Hardware-free checks for the flexible session, geometry and command interlocks."""

import json
import math
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx
from src.program.webapp2 import server, flexible_worker as worker
from src.program.webapp2.control import ControlWorkers, read_json
from src.program.webapp2.settings import ROUTINE_FILE
from webapp.launcher import write_json_atomic
from read_routines import read_routines_file


class PlaneTests(unittest.TestCase):
    def setUp(self):
        self.data = read_routines_file(ROUTINE_FILE)
        self.geometry = worker.plane_geometry(self.data)

    def test_interior_plane_point_is_eligible_for_force(self):
        pose = worker.flexible.measurement_pose(self.data, self.geometry, 500, -200)
        result = worker.classify_plane(pose, [], self.data)
        self.assertTrue(result["measurement_zone"])
        self.assertAlmostEqual(result["measurement_xy"]["X"], 500)
        self.assertAlmostEqual(result["measurement_xy"]["Y"], -200)

    def test_out_of_plane_and_wrong_orientation_are_rejected(self):
        pose = worker.flexible.measurement_pose(self.data, self.geometry, 500, -200)
        x_axis, y_axis = worker.flexible.measurement_axes(self.geometry)
        normal = worker.flexible.cross(x_axis, y_axis)
        displaced = [pose[i] + .01 * normal[i] for i in range(3)] + pose[3:]
        rotated = pose[:3] + [pose[3] + .1, *pose[4:]]
        for target in (displaced, rotated):
            self.assertFalse(worker.classify_plane(target, [], self.data)["measurement_zone"])

    def test_plane_bounds_and_nonfinite_targets_are_rejected(self):
        for x, y in ((-1, 0), (self.geometry["taught_length"] + 1, 0), (0, -401), (0, 1), (math.nan, 0), (0, math.inf)):
            with self.assertRaises(ValueError):
                worker.validate_target(x, y, self.geometry)

    def test_confirmed_extension_still_rejects_nonfinite_coordinates(self):
        worker.validate_target(-10, 20, self.geometry, outside_range_confirmed=True)
        for x, y in ((math.nan, 0), (0, math.inf)):
            with self.assertRaisesRegex(ValueError, "finite"):
                worker.validate_target(x, y, self.geometry, outside_range_confirmed=True)

    def test_confirmed_outside_moves_can_complete_and_move_back(self):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(self.data, self.geometry, 0, 0)

        def move(robot_ip, connection, target, *args):
            receiver.getActualTCPPose.return_value = target

        with patch.object(worker, "wait_until_tcp_stops"), patch.object(worker.flexible, "movel_pose", side_effect=move) as movement:
            for x, y in ((-10, 20), (self.geometry["taught_length"] + 10, -450), (100, -20)):
                worker.perform_action({"action": "move", "x": x, "y": y, "outside_range_confirmed": True}, receiver, self.data, self.geometry, Path("unused-state.json"))
                result = worker.classify_plane(receiver.getActualTCPPose(), [], self.data)
                self.assertTrue(result["in_measurement_plane"])
                self.assertAlmostEqual(result["measurement_xy"]["X"], x)
                self.assertAlmostEqual(result["measurement_xy"]["Y"], y)
            self.assertEqual(movement.call_count, 3)
        self.assertTrue(result["measurement_zone"])

    def test_unconfirmed_outside_move_and_force_outside_range_do_not_execute(self):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(self.data, self.geometry, 0, 0)
        with patch.object(worker, "wait_until_tcp_stops"), patch.object(worker.flexible, "movel_pose") as movement, patch.object(worker.flexible, "apply_force") as force:
            with self.assertRaises(ValueError):
                worker.perform_action({"action": "move", "x": -10, "y": 20}, receiver, self.data, self.geometry, Path("unused-state.json"))
            receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(self.data, self.geometry, -10, 20, allow_x_outside_taught_range=True)
            with self.assertRaisesRegex(ValueError, "configured measurement range"):
                worker.perform_action({"action": "force", "threshold": 140, "force": 160, "duration": 0}, receiver, self.data, self.geometry, Path("unused-state.json"))
            movement.assert_not_called()
            force.assert_not_called()

    def test_force_requires_a_fresh_stationary_pose_in_plane(self):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        receiver.getActualTCPPose.return_value = worker.flexible.measurement_pose(self.data, self.geometry, 500, -200)
        receiver.getActualTCPSpeed.return_value = [.1, 0, 0, 0, 0, 0]
        with self.assertRaisesRegex(TimeoutError, "TCP did not stop"):
            worker.assert_in_plane(receiver, self.data)

    def test_entry_accepts_small_speed_noise_after_reaching_start_low(self):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = self.data["waypoints"]["Home"]["q"]
        receiver.getActualTCPSpeed.return_value = [.0003, -.0002, .0001, .0004, 0, 0]

        def entry(*args):
            receiver.getActualQ.return_value = self.data["waypoints"]["p_start_l"]["q"]
            receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_start_l"]["p"]

        with patch.object(worker.flexible, "run_entry_sequence", side_effect=entry):
            worker.perform_action({"action": "start"}, receiver, self.data, self.geometry, Path("unused-state.json"))

    def test_plane_error_is_distinct_from_failure_to_settle(self):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualQ.return_value = []
        pose = worker.flexible.measurement_pose(self.data, self.geometry, 500, -200)
        pose[3] += .1
        receiver.getActualTCPPose.return_value = pose
        receiver.getActualTCPSpeed.return_value = [0] * 6
        with self.assertRaisesRegex(ValueError, "position or tool orientation"):
            worker.assert_in_plane(receiver, self.data)


class FlexibleApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workers = ControlWorkers()
        for item in (patch.object(server, "workers", self.workers), patch.object(server.legacy.state, "workers", self.workers)):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def test_flexible_page_and_options_require_no_robot_connection(self):
        with patch.object(worker, "get_rtde_receive", side_effect=AssertionError("No polling connection")):
            self.assertEqual((await self.client.get("/flexible")).status_code, 200)
            limits = (await self.client.get("/api/flexible/options")).json()
            self.assertGreater(limits["x_max"], 0)
            self.assertEqual((limits["y_min"], limits["y_max"]), (-400, 0))

    async def test_commands_require_started_session(self):
        response = await self.client.post("/api/flexible/command", json={"action": "force"})
        self.assertEqual(response.status_code, 409)

    async def test_stop_ends_ready_flexible_session_and_reports_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.workers.directory = Path(directory)
            self.workers._state_file = Path(directory) / "state.json"
            self.workers._kind = "flexible"
            process = Mock()
            process.poll.return_value = None
            self.workers._process = process
            write_json_atomic(self.workers._state_file, {"mode": "waiting_for_command"})
            with patch("webapp.worker_manager.stop_robot") as initial_stop, patch("robot_connection.stop_robot") as final_stop:
                response = await self.client.post("/api/worker/stop")
            self.assertEqual(response.status_code, 200, response.text)
            process.terminate.assert_called_once()
            initial_stop.assert_called_once()
            final_stop.assert_called_once()
            status = (await self.client.get("/api/status")).json()
            self.assertFalse(status["worker"]["running"])
            self.assertEqual(status["program_state"]["mode"], "error")
            self.assertIn("stopped by the operator while Ready", status["error"])
            self.assertTrue(status["program_state"]["notification_id"])
            response = await self.client.post("/api/flexible/command", json={"action": "force"})
            self.assertEqual(response.status_code, 409)

    async def test_command_validation(self):
        invalid = [{"action": "move", "x": 0}, {"action": "move", "x": -1, "y": 0},
                   {"action": "move", "x": 0, "y": -401}, {"action": "move", "x": 0, "y": 1},
                   {"action": "force", "duration": 9}, {"action": "force", "duration": -1},
                   {"action": "force", "force": 100, "threshold": 200},
                   {"action": "force", "server": True}]
        for payload in invalid:
            response = await self.client.post("/api/flexible/command", json=payload)
            self.assertEqual(response.status_code, 422, response.text)

    async def test_outside_range_requires_confirmation_before_queuing(self):
        with patch.object(self.workers, "send_flexible", return_value={"queued": True}) as send:
            payload = {"action": "move", "x": -10, "y": 20}
            self.assertEqual((await self.client.post("/api/flexible/command", json=payload)).status_code, 422)
            send.assert_not_called()
            payload["outside_range_confirmed"] = True
            response = await self.client.post("/api/flexible/command", json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(send.call_args.args[0]["outside_range_confirmed"])
            for field in ("x", "y"):
                invalid = {**payload, field: "nan"}
                self.assertEqual((await self.client.post("/api/flexible/command", json=invalid)).status_code, 422)

    async def test_session_blocks_other_robot_work_and_duplicate_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            self.workers.directory = Path(directory)
            self.workers._state_file = Path(directory) / "state.json"
            self.workers._kind = "flexible"
            self.workers._process = Mock()
            self.workers._process.poll.return_value = None
            write_json_atomic(self.workers._state_file, {"mode": "waiting_for_command"})
            response = await self.client.post("/api/manual/start", json={"action": "routine", "routine": "home_to_start"})
            self.assertEqual(response.status_code, 409)
            response = await self.client.post("/api/measurement/start", json={})
            self.assertEqual(response.status_code, 409)
            self.assertEqual((await self.client.post("/api/flexible/start")).status_code, 409)
            first = await self.client.post("/api/flexible/command", json={"action": "move", "x": 100, "y": -50})
            second = await self.client.post("/api/flexible/command", json={"action": "end"})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 409)
            self.assertEqual(read_json(Path(directory) / "command.json")["action"], "move")
            status = (await self.client.get("/api/status")).json()
            self.assertEqual(status["general"], "Flexible measurement: Running")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.data = read_routines_file(ROUTINE_FILE)
        self.geometry = worker.plane_geometry(self.data)
        self.pose = list(self.data["waypoints"]["p_start_h"]["p"])
        self.joints = list(self.data["waypoints"]["Home"]["q"])
        self.connections = []

    def connect(self, robot_ip):
        receiver = Mock()
        receiver.getSafetyStatusBits.return_value = 0
        receiver.getActualTCPSpeed.return_value = [0] * 6
        receiver.getActualTCPPose.side_effect = lambda: list(self.pose)
        receiver.getActualQ.side_effect = lambda: list(self.joints)
        self.connections.append(receiver)
        return receiver

    def entry(self, receiver, data, geometry, acceleration, speed):
        self.assertEqual(worker.flexible.ENTRY_SIDE, "start")
        self.pose = worker.flexible.measurement_pose(data, geometry, 0, 0)
        self.joints = list(data["waypoints"]["p_start_l"]["q"])

    def move(self, robot_ip, receiver, target, acceleration, speed, timeout):
        self.assertEqual((acceleration, speed), (.1, .1))
        self.pose = list(target)
        self.joints = [99] * 6

    def exit(self, receiver, data, geometry, acceleration, speed):
        self.pose = list(data["waypoints"]["p_start_h"]["p"])
        self.joints = list(data["waypoints"]["Home"]["q"])

    def wait_mode(self, directory, mode):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = read_json(directory / "state.json")
            if state.get("mode") == "error":
                self.fail(state.get("message"))
            if state.get("mode") == mode:
                return
            time.sleep(.01)
        self.fail(f"Did not reach {mode}: {read_json(directory / 'state.json')}")

    def test_start_move_force_miss_retry_end_and_disconnect_between_commands(self):
        errors = []
        force_attempts = 0
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            owner = ControlWorkers()
            owner.directory = directory
            owner._state_file = directory / "state.json"
            owner._kind = "flexible"
            owner._process = Mock()
            owner._process.poll.return_value = None

            def run():
                try:
                    worker.run(directory)
                except BaseException as error:
                    errors.append(error)

            def apply_force(*args, **kwargs):
                nonlocal force_attempts
                force_attempts += 1
                self.assertEqual(args[3:6], (140, 160, False))
                feedback = read_json(directory / "feedback.json")
                self.assertTrue(feedback["force_mode"])
                self.assertTrue(feedback["moving"])
                self.assertEqual(kwargs["acquisition_context"]["acquisition_label"], "local force hold")
                if force_attempts == 1:
                    return False, "first-attempt"
                self.assertEqual(kwargs["stop_method"], "timer")
                self.assertEqual(kwargs["hold_duration"], .01)
                self.assertIsNone(kwargs["acquire_data"])
                kwargs["on_force_success"]("test-time")
                return True, "test-time"

            with patch.object(worker, "assert_robot_running"), patch.object(worker, "get_rtde_receive", side_effect=self.connect), patch.object(worker, "stop_robot") as stop, patch.object(worker.flexible, "run_entry_sequence", side_effect=self.entry) as entry, patch.object(worker.flexible, "run_exit_sequence", side_effect=self.exit) as exit, patch.object(worker.flexible, "movel_pose", side_effect=self.move), patch.object(worker.flexible, "apply_force", side_effect=apply_force) as force:
                thread = threading.Thread(target=run, daemon=True)
                thread.start()
                try:
                    self.wait_mode(directory, "waiting_for_command")
                    self.connections[0].disconnect.assert_called_once()
                    self.assertFalse(read_json(directory / "feedback.json")["robot_connected"])
                    owner.send_flexible({"action": "move", "x": 500, "y": -200})
                    self.wait_mode(directory, "waiting_for_command")
                    xy = read_json(directory / "feedback.json")["measurement_xy"]
                    self.assertAlmostEqual(xy["X"], 500)
                    self.assertAlmostEqual(xy["Y"], -200)
                    owner.send_flexible({"action": "force", "threshold": 140, "force": 160, "duration": .01})
                    self.wait_mode(directory, "waiting_for_command")
                    failure = read_json(directory / "state.json")
                    self.assertFalse(failure["force_reached"])
                    self.assertIn("try again", failure["action_error"])
                    self.assertTrue(failure["notification_id"])
                    self.assertTrue(thread.is_alive())
                    with patch.object(server, "workers", owner):
                        status = server.status()
                    self.assertTrue(status["worker"]["running"])
                    self.assertIn("Contact threshold", status["error"])
                    stop.assert_not_called()
                    owner.send_flexible({"action": "force", "threshold": 140, "force": 160, "duration": .01})
                    self.wait_mode(directory, "waiting_for_command")
                    ready = read_json(directory / "state.json")
                    self.assertTrue(ready["force_reached"])
                    self.assertNotIn("action_error", ready)
                    owner.send_flexible({"action": "end"})
                    thread.join(timeout=3)
                    self.assertFalse(thread.is_alive())
                    self.assertFalse(errors, errors)
                    self.assertEqual(read_json(directory / "state.json")["mode"], "idle")
                    self.assertEqual(len(self.connections), 5)
                    for receiver in self.connections:
                        receiver.disconnect.assert_called_once()
                    entry.assert_called_once()
                    exit.assert_called_once()
                    self.assertEqual(force.call_count, 2)
                    stop.assert_not_called()
                finally:
                    if thread.is_alive():
                        write_json_atomic(directory / "command.json", {"action": "end"})
                        thread.join(timeout=3)

    def test_unsafe_start_refuses_entry_and_closes_connection(self):
        self.joints = [99] * 6
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "assert_robot_running"), patch.object(worker, "get_rtde_receive", side_effect=self.connect), patch.object(worker, "stop_robot") as stop, patch.object(worker.flexible, "run_entry_sequence") as entry:
            with self.assertRaises(RuntimeError):
                worker.run(Path(directory))
            entry.assert_not_called()
            stop.assert_called_once()
            self.connections[0].disconnect.assert_called_once()
            self.assertEqual(read_json(Path(directory) / "state.json")["mode"], "error")

    def test_force_rechecks_actual_pose_before_loading_program(self):
        receiver = self.connect("fake")
        self.pose = worker.flexible.measurement_pose(self.data, self.geometry, 500, -200)
        self.pose[3] += .2
        with tempfile.TemporaryDirectory() as directory, patch.object(worker.flexible, "apply_force") as force:
            with self.assertRaisesRegex(ValueError, "measurement plane"):
                worker.perform_action({"action": "force", "threshold": 140, "force": 160, "duration": 3}, receiver, self.data, self.geometry, Path(directory) / "state.json")
            force.assert_not_called()

    def test_contact_miss_does_not_hide_invalid_return_position(self):
        receiver = Mock()
        position = {"measurement_xy": {"X": 0, "Y": 0}}
        with patch.object(worker, "assert_in_plane", side_effect=[position, ValueError("Invalid return pose")]), patch.object(worker.flexible, "apply_force", return_value=(False, "test-time")):
            with self.assertRaisesRegex(ValueError, "Invalid return pose"):
                worker.perform_action({"action": "force", "threshold": 140, "force": 160, "duration": 0}, receiver, self.data, self.geometry, Path("unused-state.json"))


if __name__ == "__main__":
    unittest.main()
