import json
import unittest

from server_control import AcquisitionControlServer
from server_state import protocol_state_response


class ProtocolStateResponseTests(unittest.TestCase):
    def test_moving_t_f_strings_become_json_booleans(self):
        base_snapshot = {
            "context": {"measurement_index": 1},
            "state": {"tcp_position": {"X": 1, "Y": 11}, "moving": "T"},
        }

        self.assertIs(protocol_state_response(base_snapshot)["Moving"], True)

        base_snapshot["state"]["moving"] = "F"
        self.assertIs(protocol_state_response(base_snapshot)["Moving"], False)


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

    def test_isready_returns_json_boolean_tokens(self):
        server = AcquisitionControlServer("127.0.0.1", 0, 1.0)
        try:
            self.assertEqual(server._handle_request({"message": "ISREADY"}), "false")
            server.state.begin_force_hold({})
            self.assertEqual(server._handle_request({"message": "ISREADY"}), "true")
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
