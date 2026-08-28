"""TCP listener used by the main robot program for acquisition control.

The robot program owns this server. An external acquisition client connects and
sends `ALIVE`, `ISREADY`, or `GO`. Replies are intentionally short plain-text
tokens because the client program expects that lightweight protocol.
"""

import json
import socket
import threading
from pathlib import Path
from typing import Any, Callable

try:
    from .state import AcquisitionControlState
except ImportError:
    from state import AcquisitionControlState


CONFIG_SERVER_FILE = Path(__file__).resolve().parent / "config_server.json"
SHORT_RESPONSES = {"ACK", "OK", "T", "F"}
EXTENDED_RESPONSE_TERMINATOR = "\r\n"
ACCEPT_TIMEOUT = 0.5
CLIENT_READ_TIMEOUT = 5.0


def read_server_config(path: str | Path = CONFIG_SERVER_FILE) -> dict[str, Any]:
    """Read the host/port settings for the main-program control server."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def format_address(address) -> str:
    """Return a compact address label for TCP status messages."""

    if isinstance(address, tuple) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    return str(address)


def format_request(request: dict[str, Any]) -> str:
    """Return a readable request string without losing JSON payload detail."""

    if set(request) == {"message"}:
        return str(request["message"])
    return json.dumps(request, ensure_ascii=True, sort_keys=True)


def parse_request(data: bytes) -> dict[str, Any]:
    """Parse one plain-text or JSON command from the TCP client."""

    text = data.decode("utf-8").strip()
    if not text:
        raise ValueError("Empty request.")
    try:
        request = json.loads(text)
    except json.JSONDecodeError:
        request = {"message": text}
    if not isinstance(request, dict):
        raise ValueError("Request must be a JSON object or command text.")
    return request


def log_tcp_event(address, text: str) -> None:
    """Print one operator-visible TCP status line."""

    print(f"Data acquisition client {format_address(address)}: {text}")


class AcquisitionControlServer:
    """Own the TCP listener used by the measurement program.

    The rest of the program only needs a few lifecycle methods:
    start listening, stop listening, wait for the first ALIVE, and wait for GO
    during a force-hold measurement. Keeping those operations in one class ties
    the socket, listener thread, and shared state together.

    Internally the server accepts a client connection, loops over incoming
    commands, sends the short protocol response, and logs what happened for the
    operator.
    """

    def __init__(
        self,
        host: str,
        port: int,
        go_timeout: float,
        state_provider: Callable[[], dict[str, Any] | None] | None = None,
    ):
        self.host = host
        self.port = port
        self.go_timeout = go_timeout
        self.state = AcquisitionControlState(state_provider)
        self._stop_event = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((host, port))
        self._socket.listen()
        self._socket.settimeout(ACCEPT_TIMEOUT)
        self._thread = threading.Thread(
            target=self._listen,
            name="data-acquisition-control-server",
            daemon=True,
        )

    def start(self) -> None:
        """Start listening in the background."""

        self._thread.start()

    def stop(self) -> None:
        """Stop listening and unblock any force-hold wait."""

        self._stop_event.set()
        self.state.end_force_hold()
        try:
            self._socket.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def wait_for_go(self, context: dict[str, Any]) -> dict[str, Any]:
        """Callback used by apply_force after force has been reached."""

        return self.state.wait_for_go(context, self.go_timeout)

    def wait_for_client_ready(self, timeout: float) -> None:
        """Wait until the external client sends ALIVE."""

        self.state.wait_for_client_ready(timeout)

    def _listen(self) -> None:
        """Accept clients until stop() closes the server socket."""

        while not self._stop_event.is_set():
            try:
                connection, address = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._serve_client,
                args=(connection, address),
                daemon=True,
            ).start()

    def _serve_client(self, connection: socket.socket, address) -> None:
        """Read client commands, send replies, and log the connection lifecycle."""

        log_tcp_event(address, "connected")
        with connection:
            connection.settimeout(CLIENT_READ_TIMEOUT)
            try:
                for request in self._read_requests(connection):
                    log_tcp_event(address, f"received {format_request(request)}")
                    response = self._handle_request(request)
                    self._send_response(connection, response)
                    log_tcp_event(address, f"sent {response}")
            except Exception as error:
                response = f"ERR {type(error).__name__}: {error}"
                try:
                    self._send_response(connection, response)
                    log_tcp_event(address, f"sent {response}")
                except OSError:
                    pass
        log_tcp_event(address, "disconnected")

    def _read_requests(self, connection: socket.socket):
        """Yield parsed requests from one connected client."""

        data = b""
        while not self._stop_event.is_set():
            try:
                chunk = connection.recv(4096)
            except TimeoutError:
                if data.strip():
                    yield parse_request(data)
                    data = b""
                continue
            if not chunk:
                if data.strip():
                    yield parse_request(data)
                break
            data += chunk
            while b"\n" in data:
                line, data = data.split(b"\n", 1)
                if line.strip():
                    yield parse_request(line)
            command = data.decode("utf-8", errors="ignore").strip().upper()
            if command in {"ALIVE", "ISREADY", "GO"}:
                yield {"message": command}
                data = b""

    def _handle_request(self, request: dict[str, Any]) -> str:
        """Return the short protocol response for one client request."""

        message = str(request.get("message", "")).upper()
        if message == "ISREADY":
            return "T" if self.state.snapshot()["ready"] else "F"
        if message == "GO":
            self.state.mark_go()
            return "ACK"
        if message == "ALIVE":
            self.state.mark_client_ready()
            return "OK"
        return "ERR unsupported_message"

    def _send_response(self, connection: socket.socket, response: str) -> None:
        """Send short fixed tokens bare; terminate extended responses with CRLF."""

        payload = response if response in SHORT_RESPONSES else (
            response + EXTENDED_RESPONSE_TERMINATOR
        )
        connection.sendall(payload.encode("utf-8"))


def start_acquisition_control_server(
    state_provider: Callable[[], dict[str, Any] | None] | None = None,
    config_path: str | Path = CONFIG_SERVER_FILE,
) -> tuple[AcquisitionControlServer, dict[str, Any]]:
    """Create, start, and verify the main-program acquisition control server."""

    config = read_server_config(config_path)
    server = AcquisitionControlServer(
        config["host"],
        int(config["port"]),
        float(config.get("go_timeout", config.get("request_timeout", 8.0))),
        state_provider,
    )
    try:
        server.start()
        server.wait_for_client_ready(float(config.get("client_ready_timeout", 5.0)))
    except BaseException:
        server.stop()
        raise
    return server, config
