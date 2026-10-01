"""Run the acquisition TCP server without connecting to the robot.

This is a client-integration tester for ALIVE, ISREADY, GO, and STATE. It uses
the same AcquisitionControlServer as the real measurement sequence, but feeds
it synthetic robot state instead of RTDE data.
"""

import argparse
import threading
from typing import Any

try:
    from .server_control import AcquisitionControlServer, read_server_config
except ImportError:
    from server_control import AcquisitionControlServer, read_server_config


DEFAULT_POINT = 1
DEFAULT_X = 123.0
DEFAULT_Y = 333.0
DEFAULT_GO_TIMEOUT = 3600.0


class FakeRobotState:
    """Thread-safe synthetic state exposed through the STATE command."""

    def __init__(self, point: int, x: float, y: float):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "mode": "tester",
            "measurement_index": point,
            "tcp_position": {"X": x, "Y": y},
            "moving": False,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = dict(self._state)
            state["tcp_position"] = dict(self._state["tcp_position"])
            return state

    def set_point(self, point: int) -> None:
        with self._lock:
            self._state["measurement_index"] = point

    def set_position(self, x: float, y: float) -> None:
        with self._lock:
            self._state["tcp_position"] = {"X": x, "Y": y}

    def set_moving(self, moving: bool) -> None:
        with self._lock:
            self._state["moving"] = moving

    def set_error(self, message: str | None) -> None:
        with self._lock:
            if message:
                self._state["mode"] = "error"
                self._state["message"] = message
            else:
                self._state["mode"] = "tester"
                self._state.pop("message", None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="TCP host to bind. Defaults to config_server.json.")
    parser.add_argument("--port", type=int, help="TCP port to bind. Defaults to config_server.json.")
    parser.add_argument("--point", type=int, default=DEFAULT_POINT, help="Initial STATE Point value.")
    parser.add_argument("--x", type=float, default=DEFAULT_X, help="Initial STATE X value in mm.")
    parser.add_argument("--y", type=float, default=DEFAULT_Y, help="Initial STATE Y value in mm.")
    parser.add_argument(
        "--go-timeout",
        type=float,
        default=DEFAULT_GO_TIMEOUT,
        help="How long a fake hold waits for GO before clearing ISREADY.",
    )
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Start with ISREADY=true until the client sends GO or the hold times out.",
    )
    return parser.parse_args()


def start_fake_hold(
    server: AcquisitionControlServer,
    fake_state: FakeRobotState,
) -> threading.Thread:
    """Start one fake force hold so ISREADY returns true until GO is received."""

    context = {"measurement_index": fake_state.snapshot()["measurement_index"]}

    def wait_for_go() -> None:
        try:
            print(f"Fake hold started for point {context['measurement_index']}.")
            result = server.wait_for_go(context)
            print(f"GO received: {result}")
        except TimeoutError as error:
            print(f"Fake hold timed out: {error}")

    thread = threading.Thread(target=wait_for_go, daemon=True)
    thread.start()
    return thread


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  hold                 make ISREADY return true until the client sends GO\n"
        "  point <n>            set STATE Point\n"
        "  pos <x> <y>          set STATE X/Y in mm\n"
        "  moving <on|off>      set STATE Moving\n"
        "  error <text>         set STATE Error text\n"
        "  clear-error          set STATE Error back to ok\n"
        "  state                print the current fake state\n"
        "  help                 show this help\n"
        "  quit                 stop the tester\n"
    )


def run_console(server: AcquisitionControlServer, fake_state: FakeRobotState) -> None:
    print_help()
    while True:
        try:
            command = input("server-tester> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not command:
            continue
        name, *args = command.split()
        name = name.lower()

        try:
            if name in {"quit", "exit"}:
                return
            if name == "help":
                print_help()
            elif name == "hold":
                start_fake_hold(server, fake_state)
            elif name == "point" and len(args) == 1:
                fake_state.set_point(int(args[0]))
            elif name == "pos" and len(args) == 2:
                fake_state.set_position(float(args[0]), float(args[1]))
            elif name == "moving" and len(args) == 1:
                fake_state.set_moving(args[0].lower() in {"1", "true", "t", "yes", "on"})
            elif name == "error" and args:
                fake_state.set_error(" ".join(args))
            elif name == "clear-error":
                fake_state.set_error(None)
            elif name == "state":
                print(fake_state.snapshot())
            else:
                print("Unknown command. Type 'help' for commands.")
        except ValueError as error:
            print(f"Invalid value: {error}")


def main() -> None:
    args = parse_args()
    config = read_server_config()
    host = args.host or config["host"]
    port = args.port if args.port is not None else int(config["port"])

    fake_state = FakeRobotState(args.point, args.x, args.y)
    server = AcquisitionControlServer(
        host,
        port,
        args.go_timeout,
        state_provider=fake_state.snapshot,
    )

    try:
        server.start()
        print(f"Acquisition server tester listening on {host}:{port}.")
        print("This tester does not connect to the robot or move anything.")
        if args.ready:
            start_fake_hold(server, fake_state)
        run_console(server, fake_state)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
