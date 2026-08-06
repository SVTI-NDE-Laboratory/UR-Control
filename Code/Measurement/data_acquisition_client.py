"""Client used by the robot program to request data acquisition."""

import json
import socket


def send_json_line(connection, message: dict) -> None:
    """Send one newline-terminated JSON message.

    This matches the simple protocol used by the acquisition server.
    """

    connection.sendall((json.dumps(message) + "\n").encode("utf-8"))


def read_json_line(connection) -> dict:
    """Read one newline-terminated JSON response.

    The server replies once, then the client closes the connection.
    """

    data = b""
    while not data.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            break
        data += chunk

    return json.loads(data.decode("utf-8"))


def request_data_acquisition(host: str, port: int, payload: dict, timeout: float) -> dict:
    """Ask the acquisition server to record one data point.

    Raises RuntimeError if the server does not answer with `data_acquired`.
    """

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        send_json_line(connection, payload)
        response = read_json_line(connection)

    if response.get("message") != "data_acquired":
        raise RuntimeError(f"Data acquisition failed: {response}")

    return response
