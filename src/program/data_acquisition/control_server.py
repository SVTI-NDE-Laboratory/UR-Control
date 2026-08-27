"""TCP listener used by the main robot program for acquisition control.

The robot program owns this server. An external acquisition client connects and
sends `ALIVE`, `ISREADY`, or `GO`. Replies are intentionally short plain-text
tokens because the client program expects that lightweight protocol.
"""

import json
import socketserver
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


CONFIG_SERVER_FILE = Path(__file__).resolve().parent / "config_server.json"


def read_server_config(path: str | Path = CONFIG_SERVER_FILE) -> dict[str, Any]:
    """Read the host/port settings for the main-program control server."""

    return json.loads(Path(path).read_text(encoding="utf-8"))


def json_timestamp() -> str:
    """Return a local timestamp suitable for JSON protocol responses."""

    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class AcquisitionControlState:
    """Thread-safe state shared by measurement code and TCP request handlers."""

    def __init__(self, state_provider: Callable[[], dict[str, Any] | None] | None = None):
        self._lock = threading.Lock()
        self._go_event = threading.Event()
        self._client_ready_event = threading.Event()
        self._ready = False
        self._context: dict[str, Any] = {}
        self._state_provider = state_provider

    def begin_force_hold(self, context: dict[str, Any]) -> None:
        """Expose a force-hold window and clear any previous GO signal."""

        with self._lock:
            self._context = dict(context)
            self._ready = True
            self._go_event.clear()

    def end_force_hold(self) -> None:
        """Hide the force-hold window and unblock waiters during shutdown/errors."""

        with self._lock:
            self._ready = False
            self._context = {}
            self._go_event.set()

    def mark_go(self) -> bool:
        """Accept a GO message only while the force-hold window is ready."""

        with self._lock:
            accepted = self._ready
            if accepted:
                self._go_event.set()
            return accepted

    def mark_client_ready(self) -> None:
        """Record that the external client has contacted the listener."""

        self._client_ready_event.set()

    def wait_for_client_ready(self, timeout: float) -> None:
        """Block startup until the external client sends ALIVE."""

        if not self._client_ready_event.wait(timeout):
            raise TimeoutError(
                "Timed out waiting for ALIVE from the data acquisition client."
            )

    def wait_for_go(self, context: dict[str, Any], timeout: float) -> dict[str, Any]:
        """Block until the external client sends GO for the current force hold."""

        self.begin_force_hold(context)
        started_at = time.monotonic()
        try:
            if not self._go_event.wait(timeout):
                raise TimeoutError(
                    "Timed out waiting for GO from the data acquisition client."
                )
            return {
                "message": "go_received",
                "completed_at": json_timestamp(),
                "acquisition_time": time.monotonic() - started_at,
            }
        finally:
            self.end_force_hold()

    def snapshot(self) -> dict[str, Any]:
        """Return the current force-ready flag, context, and program state."""

        with self._lock:
            ready = self._ready
            context = dict(self._context)

        program_state = None
        if self._state_provider is not None:
            try:
                program_state = self._state_provider()
            except Exception as error:
                program_state = {"error": str(error)}

        return {
            "ready": ready,
            "context": context,
            "state": program_state or {},
            "timestamp": json_timestamp(),
        }


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """TCP server with one short-lived handler thread per connection."""

    allow_reuse_address = True
    daemon_threads = True


class AcquisitionRequestHandler(socketserver.BaseRequestHandler):
    """Handle one newline-framed command from an acquisition client."""

    def handle(self) -> None:
        state: AcquisitionControlState = self.server.control_state
        try:
            request = self._read_request()
            response = self._handle_request(state, request)
        except Exception as error:
            response = f"ERR {type(error).__name__}: {error}"
        self.request.sendall((response + "\n").encode("utf-8"))

    def _read_request(self) -> dict[str, Any]:
        data = b""
        self.request.settimeout(5.0)
        while not data.endswith(b"\n"):
            chunk = self.request.recv(4096)
            if not chunk:
                break
            data += chunk
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

    def _handle_request(
        self, state: AcquisitionControlState, request: dict[str, Any]
    ) -> str:
        message = str(request.get("message", "")).upper()
        if message == "ISREADY":
            return "T" if state.snapshot()["ready"] else "F"
        if message == "GO":
            state.mark_go()
            return "ACK"
        if message == "ALIVE":
            state.mark_client_ready()
            return "OK"
        return "ERR unsupported_message"


class AcquisitionControlServer:
    """Background TCP listener for acquisition-client messages."""

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
        self._server = ThreadedTCPServer((host, port), AcquisitionRequestHandler)
        self._server.control_state = self.state
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="data-acquisition-control-server",
            daemon=True,
        )

    def start(self) -> None:
        """Start listening in the background."""

        self._thread.start()

    def stop(self) -> None:
        """Stop listening and unblock any force-hold wait."""

        self.state.end_force_hold()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)

    def wait_for_go(self, context: dict[str, Any]) -> dict[str, Any]:
        """Callback used by apply_force after force has been reached."""

        return self.state.wait_for_go(context, self.go_timeout)

    def wait_for_client_ready(self, timeout: float) -> None:
        """Wait until the external client sends ALIVE."""

        self.state.wait_for_client_ready(timeout)


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
