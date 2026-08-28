"""Shared data-acquisition state used by robot motion and TCP control."""

import threading
import time
from datetime import datetime
from typing import Any, Callable


def json_timestamp() -> str:
    """Return a local timestamp suitable for JSON status records."""

    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class AcquisitionControlState:
    """Keep the synchronization state for the acquisition control protocol.

    The robot measurement thread changes this state when force is reached and
    it is waiting for data acquisition. The TCP server thread reads or updates
    the same state when the external client sends ALIVE, ISREADY, or GO.

    This is a class because the lock, events, and flags belong together. Keeping
    them grouped avoids loose globals and makes the thread handoff explicit.
    """

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
