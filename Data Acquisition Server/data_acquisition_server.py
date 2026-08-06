"""Simulated data acquisition server.

The server waits for JSON messages from the robot control program.
When it receives `{"message": "acquire_data"}`, it waits 1-2 seconds and
responds with `{"message": "data_acquired"}`.
"""

import json
import random
import socket
import time


HOST = "127.0.0.1"
PORT = 5055


def read_json_line(connection) -> dict:
    """Read one newline-terminated JSON message.

    The control program sends exactly one request per TCP connection.
    """

    data = b""
    while not data.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            break
        data += chunk

    if not data:
        return {}

    return json.loads(data.decode("utf-8"))


def send_json_line(connection, message: dict) -> None:
    """Send one newline-terminated JSON response.

    Newline framing keeps the protocol simple and easy to debug.
    """

    connection.sendall((json.dumps(message) + "\n").encode("utf-8"))


def handle_request(request: dict) -> dict:
    """Handle one acquisition request.

    For now acquisition is simulated by waiting a random time from 1-2 seconds.
    """

    if request.get("message") != "acquire_data":
        return {"message": "error", "error": "unknown message", "request": request}

    acquisition_time = random.uniform(1.0, 2.0)
    print(f"Acquire data request: {request}")
    time.sleep(acquisition_time)

    return {
        "message": "data_acquired",
        "acquisition_time": acquisition_time,
        "request_id": request.get("request_id"),
    }


def run_server(host: str, port: int) -> None:
    """Run the simulated acquisition server forever.

    Stop it with Ctrl+C when the test session is finished.
    """

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen()

        print(f"Data acquisition server listening on {host}:{port}")

        while True:
            connection, address = server.accept()
            with connection:
                print(f"Connection from {address}")
                request = read_json_line(connection)
                if not request:
                    continue
                response = handle_request(request)
                send_json_line(connection, response)


if __name__ == "__main__":
    run_server(HOST, PORT)
