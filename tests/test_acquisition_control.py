import contextlib
import io
import json
import socket
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ACQUISITION_DIR = PROJECT_ROOT / "src" / "program" / "data_acquisition"
TOOLS_DATA_ACQUISITION_DIR = PROJECT_ROOT / "tools" / "data_acquisition"
if str(DATA_ACQUISITION_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_ACQUISITION_DIR))
if str(TOOLS_DATA_ACQUISITION_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DATA_ACQUISITION_DIR))

from server_control import (
    AcquisitionControlServer,
    should_log_tcp_exchange,
    should_log_tcp_response,
)
from server_state import protocol_state_response
from server_tester import (
    FakeRobotState,
    advance_fake_point,
    run_auto_measurement,
    wait_for_tester_start,
)


class ProtocolStateResponseTests(unittest.TestCase):
    def test_moving_is_opposite_of_ready_flag(self):
        snapshot = {
            "context": {"measurement_index": 1},
            "state": {"tcp_position": {"X": 1, "Y": 11}, "moving": "T"},
            "ready": False,
        }

        self.assertIs(protocol_state_response(snapshot)["Moving"], True)

        snapshot["ready"] = True
        snapshot["state"]["moving"] = "T"
        self.assertIs(protocol_state_response(snapshot)["Moving"], False)

    def test_missing_or_null_x_uses_startup_sentinel(self):
        snapshot = {
            "context": {"measurement_index": 1},
            "state": {"tcp_position": {"Y": 11}},
        }

        self.assertEqual(protocol_state_response(snapshot)["X"], -9999)

        snapshot["state"]["tcp_position"]["X"] = None
        self.assertEqual(protocol_state_response(snapshot)["X"], -9999)

        snapshot["state"]["tcp_position"]["X"] = 12.5
        self.assertEqual(protocol_state_response(snapshot)["X"], 12.5)

    def test_state_point_prefers_force_hold_context_while_ready(self):
        snapshot = {
            "context": {"measurement_index": 1},
            "state": {
                "measurement_index": 2,
                "tcp_position": {"X": 10, "Y": 11},
            },
            "ready": True,
        }

        self.assertEqual(protocol_state_response(snapshot)["Point"], 1)

    def test_state_point_prefers_program_state_when_not_ready(self):
        snapshot = {
            "context": {"measurement_index": 1},
            "state": {
                "measurement_index": 2,
                "tcp_position": {"X": 10, "Y": 11},
            },
            "ready": False,
        }

        self.assertEqual(protocol_state_response(snapshot)["Point"], 2)


class AcquisitionControlServerTests(unittest.TestCase):
    def test_state_response_is_compact_json_with_boolean_moving(self):
        server = AcquisitionControlServer(
            "127.0.0.1",
            0,
            1.0,
            state_provider=lambda: {
                "measurement_index": 1,
                "tcp_position": {"X": 1, "Y": 11},
                "moving": "T",
            },
        )
        try:
            response = server._handle_request({"message": "STATE"})
        finally:
            server.stop()

        self.assertEqual(
            response,
            '{"X":1,"Y":11,"Point":1,"Moving":true,"Error":"ok"}',
        )
        self.assertIs(json.loads(response)["Moving"], True)

        server.state.begin_force_hold({"measurement_index": 1})
        response = server._handle_request({"message": "STATE"})
        self.assertEqual(
            response,
            '{"X":1,"Y":11,"Point":1,"Moving":false,"Error":"ok"}',
        )
        self.assertIs(json.loads(response)["Moving"], False)

    def test_isready_returns_t_or_f_tokens(self):
        server = AcquisitionControlServer("127.0.0.1", 0, 1.0)
        try:
            self.assertEqual(server._handle_request({"message": "ISREADY"}), "F")
            server.state.begin_force_hold({})
            self.assertEqual(server._handle_request({"message": "ISREADY"}), "T")
            self.assertEqual(server._handle_request({"message": "GO"}), "ACK")
            self.assertEqual(server._handle_request({"message": "ISREADY"}), "F")
        finally:
            server.stop()

    def test_start_first_ack_unblocks_start_wait(self):
        server = AcquisitionControlServer("127.0.0.1", 0, 1.0)
        try:
            self.assertEqual(server._handle_request({"message": "START_FIRST"}), "ACK")
            server.wait_for_start_first(0.0)
        finally:
            server.stop()

    def test_short_control_responses_are_sent_as_bare_ascii_bytes(self):
        server = AcquisitionControlServer("127.0.0.1", 0, 1.0)
        reader, writer = socket.socketpair()
        try:
            server._send_response(writer, "T")
            self.assertEqual(reader.recv(16), b"T")

            server._send_response(writer, "F")
            self.assertEqual(reader.recv(16), b"F")

            server._send_response(writer, "ACK")
            self.assertEqual(reader.recv(16), b"ACK")
        finally:
            reader.close()
            writer.close()
            server.stop()

    def test_log_filter_hides_alive_ack_and_moving_state(self):
        self.assertFalse(
            should_log_tcp_exchange({"message": "ALIVE"}, "ACK")
        )
        self.assertFalse(should_log_tcp_response("ACK"))
        self.assertFalse(
            should_log_tcp_exchange(
                {"message": "STATE"},
                '{"X":1,"Y":0,"Point":1,"Moving":true,"Error":"ok"}',
            )
        )
        self.assertTrue(
            should_log_tcp_exchange(
                {"message": "STATE"},
                '{"X":1,"Y":0,"Point":1,"Moving":false,"Error":"ok"}',
            )
        )


class AutoMeasurementTesterTests(unittest.TestCase):
    def test_tester_start_waits_for_client_and_start_first_then_publishes_point(self):
        class StartupServer:
            def __init__(self):
                self.waited_for_client = False
                self.waited_for_start_first = False

            def wait_for_client_ready(self, timeout):
                self.waited_for_client = True

            def wait_for_start_first(self):
                self.waited_for_start_first = True

        server = StartupServer()
        fake_state = FakeRobotState(point=99, x=0.0, y=0.0)

        with contextlib.redirect_stdout(io.StringIO()):
            wait_for_tester_start(
                server,
                fake_state,
                point=1,
                x=12.0,
                y=7.0,
            )

        self.assertTrue(server.waited_for_client)
        self.assertTrue(server.waited_for_start_first)
        self.assertEqual(
            fake_state.snapshot(),
            {
                "mode": "measurements",
                "measurement_index": 1,
                "tcp_position": {"X": 12.0, "Y": 7.0},
            },
        )
        self.assertEqual(
            protocol_state_response(
                {
                    "ready": False,
                    "context": {},
                    "state": fake_state.snapshot(),
                }
            ),
            {
                "X": 12.0,
                "Y": 7.0,
                "Point": 1,
                "Moving": True,
                "Error": "ok",
            },
        )

    def test_auto_measurement_advances_actual_points_along_x_axis(self):
        class ImmediateGoServer:
            def __init__(self):
                self.contexts = []
                self.waited_for_start_first = False

            def wait_for_client_ready(self, timeout):
                return None

            def wait_for_start_first(self):
                self.waited_for_start_first = True

            def wait_for_go(self, context):
                self.contexts.append(dict(context))
                return {"acquisition_time": 0.0}

        server = ImmediateGoServer()
        fake_state = FakeRobotState(point=1, x=0.0, y=7.0)

        with contextlib.redirect_stdout(io.StringIO()):
            run_auto_measurement(
                server,
                fake_state,
                points=3,
                x_start=0.0,
                x_step=5.0,
                y=7.0,
                move_seconds=0.0,
            )

        self.assertTrue(server.waited_for_start_first)
        self.assertEqual(
            server.contexts,
            [
                {"measurement_index": 1},
                {"measurement_index": 2},
                {"measurement_index": 3},
            ],
        )
        self.assertEqual(
            fake_state.snapshot(),
            {
                "mode": "idle",
                "measurement_index": 3,
                "tcp_position": {"X": 10.0, "Y": 7.0},
            },
        )

    def test_next_helper_advances_point_and_x_position(self):
        fake_state = FakeRobotState(point=1, x=10.0, y=7.0)

        state = advance_fake_point(fake_state, x_step=2.5)

        self.assertEqual(
            state,
            {
                "mode": "tester",
                "measurement_index": 2,
                "tcp_position": {"X": 12.5, "Y": 7.0},
            },
        )

        state = advance_fake_point(fake_state, count=2, x_step=2.5)
        self.assertEqual(state["measurement_index"], 4)
        self.assertEqual(state["tcp_position"]["X"], 17.5)


if __name__ == "__main__":
    unittest.main()
