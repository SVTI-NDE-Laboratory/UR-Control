"""Run the acquisition TCP server without connecting to the robot.

This is a client-integration tester for ALIVE, ISREADY, GO, and STATE. It uses
the same AcquisitionControlServer as the real measurement sequence, but feeds
it synthetic robot state instead of RTDE data.
"""

import argparse
import threading
import time
from typing import Any

try:
    from .server_control import AcquisitionControlServer, read_server_config
except ImportError:
    from server_control import AcquisitionControlServer, read_server_config


DEFAULT_POINT = 1
DEFAULT_X = 123.0
DEFAULT_Y = 333.0
DEFAULT_GO_TIMEOUT = 3600.0
DEFAULT_AUTO_POINTS = 20
DEFAULT_AUTO_MOVE_SECONDS = 3.0
DEFAULT_AUTO_X_STEP = 10.0


class FakeRobotState:
    """Thread-safe synthetic state exposed through the STATE command."""

    def __init__(self, point: int, x: float, y: float):
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "mode": "tester",
            "measurement_index": point,
            "tcp_position": {"X": x, "Y": y},
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

    def set_measurement_state(self, point: int, x: float, y: float, mode: str) -> None:
        with self._lock:
            self._state["mode"] = mode
            self._state["measurement_index"] = point
            self._state["tcp_position"] = {"X": x, "Y": y}
            self._state.pop("message", None)

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
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run a full fake measurement sequence instead of the interactive console.",
    )
    parser.add_argument(
        "--points",
        type=int,
        default=DEFAULT_AUTO_POINTS,
        help="Number of fake measurement points for --auto.",
    )
    parser.add_argument(
        "--move-seconds",
        type=float,
        default=DEFAULT_AUTO_MOVE_SECONDS,
        help="Seconds spent moving between fake measurement points for --auto.",
    )
    parser.add_argument(
        "--x-step",
        type=float,
        default=DEFAULT_AUTO_X_STEP,
        help="X-axis distance in mm between fake measurement points for --auto.",
    )
    parser.add_argument(
        "--wait-for-alive",
        action="store_true",
        help="In --auto mode, wait for ALIVE before starting point 1.",
    )
    parser.add_argument(
        "--no-start-prompt",
        action="store_true",
        help="In --auto mode, start measurements immediately after ALIVE.",
    )
    args = parser.parse_args()
    if args.auto and args.ready:
        parser.error("--ready cannot be combined with --auto.")
    return args


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


def wait_for_fake_hold(
    server: AcquisitionControlServer,
    point: int,
    x: float,
) -> bool:
    """Expose one fake force hold and wait until the client sends GO."""

    print(f"Point {point}: force reached at X={x:.3f} mm; waiting for GO.")
    try:
        result = server.wait_for_go({"measurement_index": point})
    except TimeoutError as error:
        print(f"Point {point}: timed out waiting for GO: {error}")
        return False

    print(f"Point {point}: GO received after {result['acquisition_time']:.3f} s.")
    return True


def move_to_next_point(
    fake_state: FakeRobotState,
    point: int,
    start_x: float,
    end_x: float,
    y: float,
    move_seconds: float,
) -> None:
    """Update fake STATE while moving along the X axis."""

    started_at = time.monotonic()
    print(
        f"Moving to point {point}: X {start_x:.3f} -> {end_x:.3f} mm "
        f"over {move_seconds:.3f} s."
    )
    while True:
        elapsed = time.monotonic() - started_at
        fraction = min(elapsed / move_seconds, 1.0) if move_seconds > 0 else 1.0
        current_x = start_x + (end_x - start_x) * fraction
        fake_state.set_measurement_state(point, current_x, y, "moving")
        if fraction >= 1.0:
            return
        time.sleep(min(0.1, move_seconds - elapsed))


def run_auto_measurement(
    server: AcquisitionControlServer,
    fake_state: FakeRobotState,
    *,
    points: int,
    x_start: float,
    x_step: float,
    y: float,
    move_seconds: float,
    wait_for_alive: bool,
    start_prompt: bool,
) -> None:
    """Run a fake 1..N measurement sequence without robot hardware."""

    if points < 1:
        raise ValueError("--points must be at least 1.")
    if move_seconds < 0:
        raise ValueError("--move-seconds must not be negative.")

    if wait_for_alive:
        print("Waiting for ALIVE before starting fake measurement sequence.")
        server.wait_for_client_ready(None)
        print("Acquisition client connected.")

    if start_prompt:
        input("Press Enter to start fake measurements, or Ctrl+C to cancel.")

    current_x = x_start
    fake_state.set_measurement_state(1, current_x, y, "measurements")
    print(
        f"Starting fake measurement sequence: points 1..{points}, "
        f"X start {x_start:.3f} mm, X step {x_step:.3f} mm."
    )

    for point in range(1, points + 1):
        point_x = x_start + (point - 1) * x_step
        fake_state.set_measurement_state(point, point_x, y, "measurements")
        if not wait_for_fake_hold(server, point, point_x):
            fake_state.set_error(f"Timed out waiting for GO at point {point}.")
            return

        if point == points:
            break

        next_point = point + 1
        next_x = x_start + point * x_step
        move_to_next_point(
            fake_state,
            next_point,
            point_x,
            next_x,
            y,
            move_seconds,
        )
        current_x = next_x

    fake_state.set_measurement_state(points, current_x, y, "measurements_done")
    print("Fake measurement sequence complete.")


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  hold                 make ISREADY return T until the client sends GO\n"
        "  point <n>            set STATE Point\n"
        "  pos <x> <y>          set STATE X/Y in mm\n"
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
        if args.auto:
            run_auto_measurement(
                server,
                fake_state,
                points=args.points,
                x_start=args.x,
                x_step=args.x_step,
                y=args.y,
                move_seconds=args.move_seconds,
                wait_for_alive=args.wait_for_alive,
                start_prompt=not args.no_start_prompt,
            )
        else:
            run_console(server, fake_state)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
