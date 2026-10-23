"""Script delivery drains controller data before closing the socket."""

import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/robot"))
import robot_connection


class ScriptDeliveryTests(unittest.TestCase):
    def test_fragmented_controller_data_is_read_before_close(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.side_effect = [b"x" * 20, b"x" * 59]
        with patch.object(robot_connection.socket, "create_connection", return_value=connection):
            robot_connection.send_script("robot", "def motion():\n  sync()\nend")
        connection.sendall.assert_called_once_with(b"def motion():\n  sync()\nend\n")
        self.assertEqual(connection.recv.call_args_list, [call(79), call(59)])
        self.assertLess(
            connection.mock_calls.index(call.recv(59)),
            connection.mock_calls.index(call.__exit__(None, None, None)))

    def test_early_close_or_read_timeout_is_reported_without_resending(self):
        for replies, error in (([b"x" * 20, b""], ConnectionError), ([socket.timeout("read timed out")], TimeoutError)):
            with self.subTest(error=error):
                connection = MagicMock()
                connection.__enter__.return_value = connection
                connection.recv.side_effect = replies
                with patch.object(robot_connection.socket, "create_connection", return_value=connection):
                    with self.assertRaises(error):
                        robot_connection.send_script("robot", "sync()\n")
                connection.sendall.assert_called_once_with(b"sync()\n")
                connection.__exit__.assert_called_once()

    def test_total_read_deadline_expires_even_with_partial_data(self):
        connection = MagicMock()
        connection.__enter__.return_value = connection
        connection.recv.return_value = b"x" * 20
        with patch.object(robot_connection.socket, "create_connection", return_value=connection), patch.object(robot_connection.time, "monotonic", side_effect=[0.0, 1.0, 5.1]):
            with self.assertRaisesRegex(TimeoutError, "execution is unconfirmed"):
                robot_connection.send_script("robot", "sync()\n")
        connection.recv.assert_called_once_with(79)


if __name__ == "__main__":
    unittest.main()
