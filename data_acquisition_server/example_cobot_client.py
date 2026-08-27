"""Interactive example client that behaves like the cobot program.

Run `data_acquisition_server.py` in another terminal first. This script then
walks through the communication protocol one message at a time:

1. Startup handshake.
2. Periodic heartbeat.
3. Operator-confirmed fake force/acquisition requests.

The fake force does not move anything. Pressing Enter only sends an
`acquire_data` message to the server, just like the real cobot program does
after the force threshold is reached.
"""

import argparse
import json
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parent
CONFIG_SERVER_FILE = SERVER_DIR / "config_server.json"
PROTOCOL_VERSION = 1
CLIENT_NAME = "example_cobot_client"


def send_json_line(connection, message: dict) -> None:
    """Send one JSON object followed by a newline."""

    encoded = json.dumps(message) + "\n"
    print(f"-> {encoded.strip()}")
    connection.sendall(encoded.encode("utf-8"))


def read_json_line(connection) -> dict:
    """Read one newline-terminated JSON response."""

    data = b""
    while not data.endswith(b"\n"):
        chunk = connection.recv(4096)
        if not chunk:
            break
        data += chunk

    if not data:
        raise ConnectionError("Server closed the connection without a response.")

    response = json.loads(data.decode("utf-8"))
    print(f"<- {json.dumps(response)}")
    return response


def exchange_message(host: str, port: int, payload: dict, timeout: float) -> dict:
    """Open one TCP connection, send one request, read one response, then close."""

    with socket.create_connection((host, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        send_json_line(connection, payload)
        return read_json_line(connection)


def protocol_step(title: str) -> None:
    print(f"\n=== {title} ===")


def handshake(host: str, port: int, timeout: float) -> None:
    protocol_step("1. Startup handshake")
    response = exchange_message(
        host,
        port,
        {
            "message": "handshake",
            "client": CLIENT_NAME,
            "protocol_version": PROTOCOL_VERSION,
        },
        timeout,
    )
    if (
        response.get("message") != "handshake_ack"
        or response.get("server") != "data_acquisition_server"
        or response.get("protocol_version") != PROTOCOL_VERSION
    ):
        raise RuntimeError(f"Unexpected handshake response: {response}")
    print("Handshake accepted.")


def heartbeat_once(host: str, port: int, timeout: float) -> None:
    heartbeat_id = uuid.uuid4().hex
    response = exchange_message(
        host,
        port,
        {
            "message": "heartbeat",
            "client": CLIENT_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "heartbeat_id": heartbeat_id,
            "sent_at": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        },
        timeout,
    )
    if (
        response.get("message") != "heartbeat_ack"
        or response.get("heartbeat_id") != heartbeat_id
    ):
        raise RuntimeError(f"Unexpected heartbeat response: {response}")


def start_heartbeat_thread(
    host: str,
    port: int,
    interval: float,
    timeout: float,
) -> tuple[threading.Event, threading.Thread]:
    """Start periodic heartbeats while the fake cobot session is active."""

    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.wait(interval):
            try:
                heartbeat_once(host, port, timeout)
            except Exception as error:
                print(f"Heartbeat failed: {error}")

    thread = threading.Thread(target=run, name="example-heartbeat", daemon=True)
    thread.start()
    return stop_event, thread


def acquire_fake_force(
    host: str,
    port: int,
    timeout: float,
    measurement_index: int,
    line_position: float,
) -> None:
    """Send one fake force/acquisition request."""

    protocol_step(f"3. Fake force reached for measurement {measurement_index}")
    request_id = uuid.uuid4().hex
    response = exchange_message(
        host,
        port,
        {
            "message": "acquire_data",
            "request_id": request_id,
            "measurement_index": measurement_index,
            "line_position": line_position,
            "fake_force": True,
            "force_message": "operator confirmed fake force",
        },
        timeout,
    )
    if (
        response.get("message") != "data_acquired"
        or response.get("request_id") != request_id
    ):
        raise RuntimeError(f"Unexpected acquisition response: {response}")
    print("Server confirmed data_acquired.")


def prompt_action(measurement_index: int, line_position: float) -> str:
    """Return the operator's next requested action."""

    prompt = (
        f"\nMeasurement {measurement_index} at {line_position:.3f} mm.\n"
        "Press Enter to apply fake force and request acquisition, "
        "'s' to skip this point, or 'q' to quit: "
    )
    return input(prompt).strip().lower()


def load_default_endpoint() -> tuple[str, int]:
    config = json.loads(CONFIG_SERVER_FILE.read_text(encoding="utf-8"))
    return config["host"], config["port"]


def parse_args() -> argparse.Namespace:
    host, port = load_default_endpoint()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=host)
    parser.add_argument("--port", type=int, default=port)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--heartbeat-interval", type=float, default=2.0)
    parser.add_argument("--heartbeat-timeout", type=float, default=1.0)
    parser.add_argument("--measurements", type=int, default=3)
    parser.add_argument("--increment", type=float, default=100.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.measurements < 1:
        raise ValueError("--measurements must be at least 1.")
    if args.increment < 0:
        raise ValueError("--increment must not be negative.")

    print(f"Connecting to data acquisition server at {args.host}:{args.port}")
    handshake(args.host, args.port, args.timeout)

    protocol_step("2. Heartbeat")
    print(
        "Starting periodic heartbeat. It uses separate short TCP connections, "
        "so it can continue while acquisition requests are in progress."
    )
    heartbeat_stop, heartbeat_thread = start_heartbeat_thread(
        args.host,
        args.port,
        args.heartbeat_interval,
        args.heartbeat_timeout,
    )

    try:
        for measurement_index in range(1, args.measurements + 1):
            line_position = (measurement_index - 1) * args.increment
            action = prompt_action(measurement_index, line_position)
            if action == "q":
                print("Operator stopped the fake cobot client.")
                break
            if action == "s":
                print("Skipped. No message sent to the server for this point.")
                continue
            acquire_fake_force(
                args.host,
                args.port,
                args.timeout,
                measurement_index,
                line_position,
            )
            time.sleep(0.2)
    finally:
        protocol_step("4. Shutdown")
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        print("Heartbeat stopped. Client session closed.")


if __name__ == "__main__":
    main()
