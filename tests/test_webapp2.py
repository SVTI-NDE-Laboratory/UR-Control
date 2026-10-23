"""WebApp 2.0 integration/interlock tests. No physical robot is contacted."""

import json
import socket
import subprocess
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
from src.program.webapp2 import server, manual_worker, measurement_worker
from src.program.webapp2.control import ControlWorkers
from src.program.webapp2.feedback import classify_position, Feedback, TrackedServer
from src.program.webapp2.settings import ROUTINE_FILE
from read_routines import read_routines_file


def geometry():
    return {"waypoints": {"p_start_l": {"p": [0, 0, 0, 0, 0, 0]},
                          "p_end_l": {"p": [1, 0, 0, 0, 0, 0]}}, "routines": []}


class ZoneTests(unittest.TestCase):
    def test_accepts_endpoints_and_segment_interior(self):
        for x in (0, 0.5, 1):
            self.assertTrue(classify_position([x, 0, 0, 0, 0, 0], [], geometry())["measurement_zone"])

    def test_rejects_wrong_height_off_line_and_outside_segment(self):
        for pose in ([0.5, 0, .01, 0, 0, 0], [.5, .01, 0, 0, 0, 0], [1.01, 0, 0, 0, 0, 0], [-.01, 0, 0, 0, 0, 0]):
            self.assertFalse(classify_position(pose, [], geometry())["measurement_zone"])

    def test_rejects_wrong_tool_orientation(self):
        self.assertFalse(classify_position([.5, 0, 0, 0, .1, 0], [], geometry())["measurement_zone"])

    def test_real_installation_endpoints(self):
        data = read_routines_file(ROUTINE_FILE)
        for name in ("p_start_l", "p_end_l"):
            point = data["waypoints"][name]
            self.assertTrue(classify_position(point["p"], point["q"], data)["measurement_zone"])

    def test_degenerate_zone_fails_closed(self):
        data = geometry()
        data["waypoints"]["p_end_l"]["p"][0] = 0
        with self.assertRaises(ValueError):
            classify_position([0] * 6, [], data)


class ManualWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = read_routines_file(ROUTINE_FILE)
        self.receiver = Mock()
        self.receiver.getSafetyStatusBits.return_value = 0
        self.receiver.getActualTCPSpeed.return_value = [0] * 6
        self.receiver.getActualQ.return_value = self.data["waypoints"]["p_start_l"]["q"]
        self.receiver.getActualTCPPose.return_value = self.data["waypoints"]["p_start_l"]["p"]
        self.receiver.getActualTCPSpeed.return_value = [0] * 6

    def run_action(self, request):
        with patch.object(manual_worker, "assert_robot_running"), patch.object(manual_worker, "get_rtde_receive", return_value=self.receiver):
            manual_worker.run(request, self.directory)

    def test_linear_units_and_cleanup(self):
        with patch.object(manual_worker, "movel_pose") as move:
            self.run_action({"action": "waypoint", "waypoint": "p_start_l", "motion": "l", "speed": 150, "acceleration": 100})
        self.assertEqual(move.call_args.args[3:5], (.1, .15))
        self.assertEqual(move.call_args.args[5], 60.0)
        self.receiver.disconnect.assert_called_once()
        feedback = json.loads((self.directory / "feedback.json").read_text())
        self.assertFalse(feedback["robot_connected"])
        self.assertTrue(feedback["measurement_zone"])

    def test_joint_units_remain_radians(self):
        self.receiver.getActualQ.return_value = self.data["waypoints"]["home_to_start1"]["q"]
        with patch.object(manual_worker, "movej") as move:
            self.run_action({"action": "waypoint", "waypoint": "Home", "motion": "j", "speed": .05, "acceleration": .1})
        self.assertEqual(move.call_args.args[3:5], (.1, .05))
        self.assertEqual(move.call_args.args[6], 60.0)

    def test_routine_wrong_start_never_runs(self):
        with patch.object(manual_worker, "assert_at_routine_first_waypoint", side_effect=RuntimeError("wrong start")), patch.object(manual_worker, "run_routine") as run, patch.object(manual_worker, "stop_robot"):
            with self.assertRaisesRegex(RuntimeError, "wrong start"):
                self.run_action({"action": "routine", "routine": "home_to_start"})
        run.assert_not_called()
        self.receiver.disconnect.assert_called_once()

    def test_manual_worker_rejects_force(self):
        with patch.object(manual_worker, "stop_robot"):
            with self.assertRaisesRegex(ValueError, "Unknown manual action"):
                self.run_action({"action": "force"})
        self.receiver.disconnect.assert_called_once()


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.workers = ControlWorkers()
        self.old_config = server.legacy.state.get_config()
        self.patches = [patch.object(server, "workers", self.workers), patch.object(server.legacy.state, "workers", self.workers)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(server.legacy.state.set_config, self.old_config) if self.old_config else self.addCleanup(server.legacy.state.clear_config)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def test_pages_and_idle_status_do_not_connect_robot(self):
        with patch("robot_connection.get_rtde_receive", side_effect=AssertionError("Unexpected connection")):
            for route in ("/manual", "/flexible", "/automatic", "/settings", "/configuration", "/api/status", "/api/measurement", "/api/manual/options", "/api/flexible/options"):
                response = await self.client.get(route)
                self.assertEqual(response.status_code, 200, response.text)
            status = (await self.client.get("/api/status")).json()
            self.assertFalse(status["feedback"]["robot_connected"])
            self.assertIsNone(status["feedback"]["moving"])

    async def test_routine_file_is_locked_in_api_and_form(self):
        files = (await self.client.get("/api/configuration/routine-files")).json()
        self.assertEqual(files["files"], [ROUTINE_FILE.name])
        self.assertEqual((await self.client.post("/api/configuration/routine-file", json={"routine_file": "routine_mira.json"})).status_code, 403)
        page = (await self.client.get("/configuration")).text
        self.assertNotIn('<select id="routine-file"', page)
        self.assertNotIn('<label for="routine-file">', page)
        script = (await self.client.get('/v2-static/automatic.js')).text
        self.assertIn("const routineFileSelect = document.createElement('select');", script)
        self.assertNotIn('routineFileSelect.disabled = controlsLocked;', script)

    async def test_automatic_confirmations_use_the_shared_dialog(self):
        page = (await self.client.get("/configuration")).text
        script = (await self.client.get('/v2-static/automatic.js')).text
        self.assertNotIn("window.confirm(", page + script)
        self.assertNotIn("window.alert(", page + script)
        self.assertIn("if (!await window.confirmAppAction(", script)
        self.assertIn("const confirmed = await window.confirmAppAction(", script)
        self.assertIn("'Save measurement defaults', 'Save as default'", script)
        self.assertIn("'Start robot motion', 'Start program'", script)
        self.assertIn('src="/v2-static/automatic.js"', page)
        self.assertIn('Measurements folder name', page)
        self.assertNotIn('id="output-directory"', page)
        self.assertNotIn('id="browse-output"', page)
        self.assertIn('src="/v2-static/dialogs.js"', page)
        self.assertIn('href="/v2-static/dialogs.css"', page)
        shell = (await self.client.get("/automatic")).text
        self.assertLess(shell.index('/v2-static/dialogs.js'), shell.index('/v2-static/app.js'))
        for asset in ("dialogs.js", "dialogs.css"):
            self.assertEqual((await self.client.get('/v2-static/' + asset)).status_code, 200)

    async def test_request_validation_rejects_invalid_actions(self):
        invalid = [{"action": "waypoint", "waypoint": "missing"},
                   {"action": "waypoint", "waypoint": "Home", "motion": "l"},
                   {"action": "waypoint", "waypoint": "Home", "motion": "j", "speed": 100},
                   {"action": "force", "threshold": 200, "force": 100},
                   {"action": "force", "force": -1}, {"action": "routine", "routine": "missing"},
                   {"action": "force", "routine_file": "other.json"}]
        for body in invalid:
            response = await self.client.post("/api/manual/start", json=body)
            self.assertEqual(response.status_code, 422, response.text)

    async def test_manual_and_automatic_cannot_overlap(self):
        process = Mock()
        process.poll.return_value = None
        self.workers._process = process
        self.workers._kind = "measurement"
        response = await self.client.post("/api/manual/start", json={"action": "routine", "routine": "home_to_start"})
        self.assertEqual(response.status_code, 409)
        response = await self.client.post("/api/measurement/start", json={})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((await self.client.post("/api/flexible/start")).status_code, 409)

    async def test_running_program_locks_other_pages_until_worker_ends(self):
        process = Mock()
        process.poll.return_value = None
        self.workers._process = process
        for kind, allowed in (("flexible", "/flexible"), ("measurement", "/automatic")):
            self.workers._kind = kind
            for route in ("/manual", "/flexible", "/automatic", "/settings"):
                response = await self.client.get(route)
                if route == allowed:
                    self.assertEqual(response.status_code, 200)
                else:
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(response.headers["location"], allowed)
        self.workers._process = None
        for route in ("/manual", "/flexible", "/automatic", "/settings"):
            self.assertEqual((await self.client.get(route)).status_code, 200)

    async def test_manual_motion_options_and_api_enforce_waypoint_rules(self):
        points = (await self.client.get("/api/manual/options")).json()["waypoints"]
        by_name = {point["name"]: point for point in points}
        for name in ("Home", "home_to_start1", "end_to_home1"):
            self.assertFalse(by_name[name]["linear"])
            self.assertTrue(by_name[name]["joint"])
            response = await self.client.post("/api/manual/start", json={"action": "waypoint", "waypoint": name, "motion": "l"})
            self.assertEqual(response.status_code, 422)
        for name in ("p_start_l", "p_end_l"):
            self.assertTrue(by_name[name]["linear"])
            self.assertFalse(by_name[name]["joint"])
            response = await self.client.post("/api/manual/start", json={"action": "waypoint", "waypoint": name, "motion": "j", "speed": .05, "acceleration": .1})
            self.assertEqual(response.status_code, 422)
        for name in ("p_start_h", "p_end_h"):
            self.assertTrue(by_name[name]["linear"])
            self.assertTrue(by_name[name]["joint"])

    async def test_manual_force_is_no_longer_exposed(self):
        response = await self.client.post("/api/manual/start", json={"action": "force", "server": True})
        self.assertEqual(response.status_code, 422)
        self.assertEqual((await self.client.post("/api/acquisition/connect")).status_code, 404)

    async def test_completed_worker_crash_is_visible(self):
        process = Mock(returncode=9)
        process.poll.return_value = 9
        self.workers._process = process
        status = (await self.client.get("/api/status")).json()
        self.assertIn("9", status["error"])
        self.assertFalse(status["feedback"]["robot_connected"])

    async def test_waypoints_put_named_endpoints_first_and_preserve_other_order(self):
        names = ["middle_b", "p_end_l", "Home", "middle_a", "p_start_l", "p_end_h", "p_start_h"]
        data = {"waypoints": {name: {"q": [0] * 6} for name in names}, "routines": []}
        with patch.object(server, "read_routines_file", return_value=data):
            response = await self.client.get("/api/manual/options")
        self.assertEqual([point["name"] for point in response.json()["waypoints"]],
                         ["Home", "p_start_h", "p_start_l", "p_end_h", "p_end_l", "middle_b", "middle_a"])
        del data["waypoints"]["p_end_h"]
        with patch.object(server, "read_routines_file", return_value=data):
            response = await self.client.get("/api/manual/options")
        self.assertEqual([point["name"] for point in response.json()["waypoints"]],
                         ["Home", "p_start_h", "p_start_l", "p_end_l", "middle_b", "middle_a"])

    async def test_stop_delegates_to_shared_worker(self):
        with patch.object(server.legacy, "stop_worker", return_value={"stopped": True}) as stop:
            response = await self.client.post("/api/worker/stop")
        self.assertEqual(response.status_code, 200)
        stop.assert_called_once()

    async def test_waypoint_confirmation_requires_matching_waiting_worker(self):
        body = {"state_file": "old/state.json", "proceed": True}
        self.assertEqual((await self.client.post("/api/manual/confirm-waypoint", json=body)).status_code, 409)
        with tempfile.TemporaryDirectory() as temporary:
            self.workers.directory = Path(temporary)
            self.workers._state_file = Path(temporary) / "state.json"
            self.workers._state_file.write_text(json.dumps({"mode": "waiting_for_waypoint_confirmation"}))
            self.workers._kind = "manual"
            self.workers._process = Mock()
            self.workers._process.poll.return_value = None
            body["state_file"] = str(self.workers._state_file)
            body["proceed"] = False
            response = await self.client.post("/api/manual/confirm-waypoint", json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(json.loads((Path(temporary) / "waypoint_confirmation.json").read_text()), {"proceed": False})
            self.assertEqual((await self.client.post("/api/manual/confirm-waypoint", json=body)).status_code, 409)


class AcquisitionTests(unittest.TestCase):
    def test_tcp_connection_led_clears_after_disconnect(self):
        server = TrackedServer("127.0.0.1", 0, 1, state_provider=lambda: {"mode": "idle"})
        server.start()
        try:
            with socket.create_connection(server._socket.getsockname(), timeout=2) as client:
                client.sendall(b"ALIVE\n")
                self.assertEqual(client.recv(3), b"ACK")
                self.assertEqual(server.clients, 1)
                server.state.begin_force_hold({"measurement_index": 1})
                client.sendall(b"ISREADY\n")
                self.assertEqual(client.recv(1), b"T")
                client.sendall(b"GO\n")
                self.assertEqual(client.recv(3), b"ACK")
                self.assertFalse(server.state.snapshot()["ready"])
            deadline = time.monotonic() + 2
            while server.clients and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(server.clients, 0)
        finally:
            server.stop()


class LifecycleTests(unittest.TestCase):
    def test_real_http_server_serves_pages_assets_and_status(self):
        import uvicorn
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        host = uvicorn.Server(uvicorn.Config(server.api, log_level="error"))
        thread = threading.Thread(target=host.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not host.started and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(host.started)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
                for path in ("/manual", "/flexible", "/automatic", "/configuration", "/static/styles.css", "/v2-static/app.js", "/v2-static/styles.css", "/api/status"):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, path)
        finally:
            host.should_exit = True
            thread.join(timeout=5)
            listener.close()

    def test_automatic_entry_point_imports_in_a_fresh_process(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-m", "src.program.webapp2.measurement_worker", "--output-dir", directory, "--help"],
                                    cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--start-signal-file", result.stdout)
            feedback = json.loads((Path(directory) / "feedback.json").read_text())
            self.assertFalse(feedback["robot_connected"])

    def test_manual_worker_cannot_be_started_twice(self):
        workers = ControlWorkers()
        with tempfile.TemporaryDirectory() as directory, patch("src.program.webapp2.control.RUNTIME", Path(directory)), patch.object(workers, "_spawn") as spawn:
            process = Mock()
            process.poll.return_value = None
            spawn.side_effect = lambda *args: setattr(workers, "_process", process)
            workers.start_manual({"action": "routine", "routine": "home_to_start"})
            with self.assertRaisesRegex(RuntimeError, "already running"):
                workers.start_manual({"action": "routine", "routine": "home_to_start"})
            self.assertEqual(spawn.call_count, 1)

    def test_automatic_worker_uses_fixed_file_and_isolated_config(self):
        workers = ControlWorkers()
        with tempfile.TemporaryDirectory() as directory, patch.object(workers, "_spawn") as spawn:
            output = Path(directory)
            (output / "start_movement.signal").write_text("stale")
            (output / "feedback.json").write_text('{"robot_connected": true}')
            workers.start_measurement(server.legacy.load_default_config("point_to_point"), output, False, ROUTINE_FILE)
            saved = json.loads((output / "measurement_configuration.json").read_text())
            self.assertEqual(list(saved), ["line", "obstacle", "points_selections", "force", "motion"])
            arguments = spawn.call_args.args[1]
            self.assertEqual(arguments[arguments.index("--routines-file") + 1], ROUTINE_FILE)
            self.assertEqual(arguments[arguments.index("--config") + 1], output / "measurement_configuration.json")
            self.assertFalse((output / "feedback.json").exists())
            self.assertFalse((output / "start_movement.signal").exists())

    def test_stop_terminates_worker_and_sends_final_stop_after_exit(self):
        workers = ControlWorkers()
        process = Mock()
        process.poll.return_value = None
        workers._process = process
        events = []
        process.terminate.side_effect = lambda: events.append("terminate")
        process.wait.side_effect = lambda **kwargs: events.append("wait")
        with tempfile.TemporaryDirectory() as directory:
            workers._state_file = Path(directory) / "state.json"
            with patch("robot_connection.stop_robot", side_effect=lambda *args: events.append("final_stop")), patch("webapp.worker_manager.stop_robot", side_effect=lambda *args: events.append("initial_stop")):
                workers.stop("test")
            self.assertLess(events.index("wait"), events.index("final_stop"))
            self.assertEqual(json.loads(workers._state_file.read_text())["mode"], "stopped")
            self.assertFalse(workers.snapshot()["running"])

    def test_measurement_feedback_reuses_original_connection(self):
        sys.path.insert(0, str(ROOT / "src/program/commands"))
        import run_measurement_sequence as sequence
        original_server = sequence.AcquisitionControlServer
        receiver = Mock()
        with tempfile.TemporaryDirectory() as directory:
            feedback = Mock()

            def original_workflow():
                connection = sequence.get_rtde_receive("test-robot")
                self.assertIs(connection.getActualQ(), receiver.getActualQ.return_value)
                connection.disconnect()

            # Restore the process-local hooks after this in-process worker test.
            with patch.object(sequence, "get_rtde_receive", return_value=receiver) as connect, patch.object(sequence, "main", side_effect=original_workflow), patch.object(measurement_worker, "Feedback", return_value=feedback), patch.object(sys, "argv", ["worker", "--output-dir", directory]):
                try:
                    measurement_worker.main()
                finally:
                    sequence.AcquisitionControlServer = original_server
            connect.assert_called_once_with("test-robot")
            feedback.attach.assert_called_once()
            feedback.detach.assert_called_once()
            feedback.close.assert_called_once()
            receiver.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
