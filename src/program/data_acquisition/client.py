"""Client used by the robot program to request data acquisition."""

import json
import socket
import threading
import uuid
from datetime import datetime


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

    if not data:
        raise ConnectionError("Data acquisition server closed without a response.")
    return json.loads(data.decode("utf-8"))


def exchange_message(host: str, port: int, payload: dict, timeout: float) -> dict:
    """Send one request on a bounded connection and return its response."""

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        send_json_line(connection, payload)
        return read_json_line(connection)


def handshake_data_acquisition_server(
    host: str, port: int, timeout: float
) -> dict:
    """Confirm that the expected acquisition service owns the endpoint."""

    response = exchange_message(
        host,
        port,
        {
            "message": "handshake",
            "client": "robot_main_program",
            "protocol_version": 1,
        },
        timeout,
    )
    if (
        response.get("message") != "handshake_ack"
        or response.get("server") != "data_acquisition_server"
        or response.get("protocol_version") != 1
    ):
        raise RuntimeError(f"Invalid data acquisition handshake: {response}")
    return response


def send_heartbeat(host: str, port: int, timeout: float) -> dict:
    """Notify the acquisition server that the main program is still running."""

    heartbeat_id = uuid.uuid4().hex
    response = exchange_message(
        host,
        port,
        {
            "message": "heartbeat",
            "client": "robot_main_program",
            "protocol_version": 1,
            "heartbeat_id": heartbeat_id,
            "sent_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        },
        timeout,
    )
    if (
        response.get("message") != "heartbeat_ack"
        or response.get("heartbeat_id") != heartbeat_id
    ):
        raise RuntimeError(f"Invalid data acquisition heartbeat: {response}")
    return response


def start_heartbeat_thread(
    host: str,
    port: int,
    interval: float,
    timeout: float,
) -> tuple[threading.Event, threading.Thread]:
    """Send periodic heartbeat messages until the returned stop event is set."""

    stop_event = threading.Event()

    def heartbeat_loop() -> None:
        while not stop_event.wait(interval):
            try:
                send_heartbeat(host, port, timeout)
            except Exception as error:
                print(f"Warning: data acquisition heartbeat failed: {error}")

    thread = threading.Thread(
        target=heartbeat_loop,
        name="data-acquisition-heartbeat",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def request_data_acquisition(host: str, port: int, payload: dict, timeout: float) -> dict:
    """Ask the acquisition server to record one data point.

    Raises RuntimeError if the server does not answer with `data_acquired`.
    """

    request_id = uuid.uuid4().hex
    request = {
        **payload,
        "message": "acquire_data",
        "request_id": request_id,
    }
    response = exchange_message(host, port, request, timeout)

    if (
        response.get("message") != "data_acquired"
        or response.get("request_id") != request_id
    ):
        raise RuntimeError(f"Data acquisition failed: {response}")

    return response
