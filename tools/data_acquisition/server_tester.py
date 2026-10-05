"""Run the acquisition TCP server without connecting to the robot.

This is a client-integration tester for ALIVE, START_FIRST, ISREADY,
GO, and STATE. It uses the same AcquisitionControlServer as the real
measurement sequence, but feeds it synthetic robot state instead of RTDE data.
"""

import argparse
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROGRAM_DIR = PROJECT_ROOT / "src" / "program"
if str(PROGRAM_DIR) not in sys.path:
    sys.path.insert(0, str(PROGRAM_DIR))

from data_acquisition.server_control import AcquisitionControlServer, read_server_config


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

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self._state["mode"] = mode
            if mode != "error":
                self._state.pop("message", None)

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
        help="In --auto mode, how long each fake point waits for GO.",
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
    return parser.parse_args()


def set_fake_ready(
    server: AcquisitionControlServer,
    fake_state: FakeRobotState,
) -> None:
    """Expose one manual ready window until the client sends GO."""

    context = {"measurement_index": fake_state.snapshot()["measurement_index"]}
    server.state.begin_force_hold(context)
    print(f"ISREADY=True for point {context['measurement_index']}.")
    print("It will return to False when the client sends GO.")


def wait_for_tester_start(
    server: AcquisitionControlServer,
    fake_state: FakeRobotState,
    *,
    point: int,
    x: float,
    y: float,
) -> None:
    """Mirror server-mode startup before exposing fake measurement controls."""

    print("Waiting for ALIVE before starting fake measurement sequence.")
    server.wait_for_client_ready(None)
    print("Acquisition client connected.")
    print("Waiting for START_FIRST before fake robot motion.")
    server.wait_for_start_first()
    fake_state.set_measurement_state(point, x, y, "measurements")
    print(
        "Acquisition client sent START_FIRST. "
        f"STATE Point={point}, Moving=True, ISREADY=False."
    )


def advance_fake_point(
    fake_state: FakeRobotState,
    *,
    count: int = 1,
    x_step: float = DEFAULT_AUTO_X_STEP,
) -> dict[str, Any]:
    """Advance the fake point and X position for interactive testing."""

    if count < 1:
        raise ValueError("next count must be at least 1.")

    state = fake_state.snapshot()
    point = int(state["measurement_index"]) + count
    position = state["tcp_position"]
    x = float(position["X"]) + x_step * count
    y = float(position["Y"])
    fake_state.set_measurement_state(point, x, y, state["mode"])
    return fake_state.snapshot()


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
        fake_state.set_measurement_state(point, current_x, y, "measurements")
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
) -> None:
    """Run a fake 1..N measurement sequence without robot hardware."""

    if points < 1:
        raise ValueError("--points must be at least 1.")
    if move_seconds < 0:
        raise ValueError("--move-seconds must not be negative.")

    current_x = x_start
    wait_for_tester_start(
        server,
        fake_state,
        point=1,
        x=current_x,
        y=y,
    )
    print(
        f"Starting fake measurement sequence: points 1..{points}, "
        f"X start {x_start:.3f} mm, X step {x_step:.3f} mm."
    )
    fake_state.set_measurement_state(1, current_x, y, "measurements")

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
    fake_state.set_measurement_state(points, current_x, y, "end_routine")
    fake_state.set_measurement_state(points, current_x, y, "idle")
    print("Fake measurement sequence complete.")


def print_help() -> None:
    print(
        "\nCommands:\n"
        "  ready                make ISREADY return T until the client sends GO\n"
        "  next [n]             advance STATE Point by n, default 1\n"
        "  mode <name>          set raw STATE mode\n"
        "  point <n>            set STATE Point\n"
        "  pos <x> <y>          set STATE X/Y in mm\n"
        "  error <text>         set STATE Error text\n"
        "  clear-error          set STATE Error back to ok\n"
        "  state                print the current fake state\n"
        "  help                 show this help\n"
        "  quit                 stop the tester\n"
    )


def run_console(
    server: AcquisitionControlServer,
    fake_state: FakeRobotState,
    *,
    x_step: float,
) -> None:
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
            elif name == "ready":
                set_fake_ready(server, fake_state)
            elif name == "next" and len(args) <= 1:
                count = int(args[0]) if args else 1
                state = advance_fake_point(fake_state, count=count, x_step=x_step)
                print(
                    "Advanced to point "
                    f"{state['measurement_index']} at "
                    f"X={state['tcp_position']['X']:.3f} mm."
                )
            elif name == "mode" and len(args) == 1:
                fake_state.set_mode(args[0])
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
        if args.auto:
            run_auto_measurement(
                server,
                fake_state,
                points=args.points,
                x_start=args.x,
                x_step=args.x_step,
                y=args.y,
                move_seconds=args.move_seconds,
            )
        else:
            wait_for_tester_start(
                server,
                fake_state,
                point=args.point,
                x=args.x,
                y=args.y,
            )
            run_console(server, fake_state, x_step=args.x_step)
    finally:
        server.stop()


if __name__ == "__main__":
    main()
