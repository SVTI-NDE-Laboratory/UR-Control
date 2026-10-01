import contextlib
import io
import json
import socket
import unittest

from server_control import (
    AcquisitionControlServer,
    should_log_tcp_exchange,
    should_log_tcp_response,
)
from server_state import protocol_state_response
from server_tester import FakeRobotState, run_auto_measurement


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
    def test_auto_measurement_advances_actual_points_along_x_axis(self):
        class ImmediateGoServer:
            def __init__(self):
                self.contexts = []

            def wait_for_client_ready(self, timeout):
                return None

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
                wait_for_alive=True,
                start_prompt=False,
            )

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
                "mode": "measurements_done",
                "measurement_index": 3,
                "tcp_position": {"X": 10.0, "Y": 7.0},
            },
        )


if __name__ == "__main__":
    unittest.main()
