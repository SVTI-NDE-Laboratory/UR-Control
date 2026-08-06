import argparse
import math
import socket
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTINES_DIR = ROOT / "Code" / "Routines"
if str(ROUTINES_DIR) not in sys.path:
    sys.path.insert(0, str(ROUTINES_DIR))

from read_waypoints import read_waypoints


ROBOT_IP = "192.168.3.10"
SCRIPT_PORT = 30002
DASHBOARD_PORT = 29999

SCRIPT_FILE = ROOT / "Data" / "paths_Stefan.script"
WAYPOINTS = ["Home", "Tmp1", "Tmp2", "p_start_h"]

A = 0.05
V = 1
JOINT_TOLERANCE = 0.01
WAIT_TIMEOUT = 30.0


def ur_list(values: list[float]) -> str:
    """Format a Python list as a URScript list.

    Used when building the one-move script sent to the robot.
    """

    return "[" + ", ".join(f"{value:.12g}" for value in values) + "]"


def movej_script(q: list[float], a: float, v: float) -> str:
    """Build a URScript program for a single joint move.

    Python sends this script once per waypoint so the sequence stays interactive.
    """

    return f"""def python_movej():
  movej({ur_list(q)}, a={a}, v={v})
end

python_movej()
"""


def send_script(robot_ip: str, script: str) -> None:
    """Send one URScript program to the robot.

    The robot executes it immediately through the secondary client port.
    """

    with socket.create_connection((robot_ip, SCRIPT_PORT), timeout=5) as sock:
        sock.sendall(script.encode("utf-8"))


def dashboard_command(robot_ip: str, command: str) -> str:
    """Send one read-only Dashboard command.

    Used to check remote-control state before any movement is sent.
    """

    with socket.create_connection((robot_ip, DASHBOARD_PORT), timeout=5) as sock:
        sock.recv(1024)
        sock.sendall((command + "\n").encode("utf-8"))
        return sock.recv(1024).decode("utf-8", errors="replace").strip()


def assert_remote_control(robot_ip: str) -> None:
    """Stop early if the teach pendant is not in Remote Control mode.

    This prevents Python from trying to move while the robot is in Manual/Local mode.
    """

    response = dashboard_command(robot_ip, "is in remote control").lower()
    if response.endswith("true"):
        return

    raise RuntimeError(
        "Robot is not in Remote Control mode. Switch the teach pendant from Manual/Local "
        "to Remote Control before running Python motion."
    )


def get_rtde_receive(robot_ip: str):
    """Create an RTDE receive connection.

    RTDE is used here to wait until the target joints are reached.
    """

    try:
        from rtde_receive import RTDEReceiveInterface
    except ImportError as error:
        raise RuntimeError(
            "Install ur_rtde to wait for movement completion:\n"
            "python -m pip install ur_rtde"
        ) from error

    return RTDEReceiveInterface(robot_ip)


def max_joint_error(q_actual: list[float], q_target: list[float]) -> float:
    """Return the largest absolute joint error.

    This gives one scalar value for checking whether a move is complete.
    """

    return max(abs(actual - target) for actual, target in zip(q_actual, q_target))


def wait_until_at_joint_target(
    rtde_receive,
    q_target: list[float],
    tolerance: float,
    timeout: float,
) -> list[float]:
    """Wait until actual joints match the target.

    Raises TimeoutError if the target is not reached within the configured time.
    """

    start = time.monotonic()

    while time.monotonic() - start < timeout:
        q_actual = rtde_receive.getActualQ()
        if max_joint_error(q_actual, q_target) <= tolerance:
            return q_actual
        time.sleep(0.1)

    q_actual = rtde_receive.getActualQ()
    error = max_joint_error(q_actual, q_target)
    raise TimeoutError(f"Target not reached within {timeout} s. Max joint error: {error:.4f} rad")


def print_tcp_pose(rtde_receive) -> None:
    """Print the current TCP pose.

    This lets the operator inspect the reached position after each move.
    """

    pose = rtde_receive.getActualTCPPose()
    x, y, z, rx, ry, rz = pose
    print(
        "Actual TCP pose: "
        f"x={x:.6f}, y={y:.6f}, z={z:.6f}, "
        f"rx={rx:.6f}, ry={ry:.6f}, rz={rz:.6f}"
    )


def joint_degrees(q: list[float]) -> str:
    """Format joint angles in degrees for terminal output.

    The robot still receives the original radian values.
    """

    return ", ".join(f"{math.degrees(value):.1f} deg" for value in q)


def main() -> None:
    """Run the step-by-step waypoint movement test.

    The script connects after terminal confirmation and moves one waypoint at a time.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, default=SCRIPT_FILE)
    parser.add_argument("--robot-ip", default=ROBOT_IP)
    parser.add_argument("--a", type=float, default=A)
    parser.add_argument("--v", type=float, default=V)
    parser.add_argument("--tolerance", type=float, default=JOINT_TOLERANCE)
    parser.add_argument("--timeout", type=float, default=WAIT_TIMEOUT)
    parser.add_argument("waypoints", nargs="*", default=WAYPOINTS)
    args = parser.parse_args()

    waypoints = read_waypoints(args.script, args.waypoints)
    moves = []

    for name in args.waypoints:
        data = waypoints[name]
        if "q" not in data:
            print(f"Skipping {name}: no joint target q found.")
            continue
        moves.append((name, data["q"]))

    input(
        "Python will send one movej at a time.\n"
        "After each move reaches the joint target, confirm in this terminal.\n"
        "Press Enter to connect, or Ctrl+C to cancel."
    )

    assert_remote_control(args.robot_ip)
    rtde_receive = get_rtde_receive(args.robot_ip)

    for name, q in moves:
        print(f"\nMoving to {name}")
        print(f"Target joints: {joint_degrees(q)}")

        send_script(args.robot_ip, movej_script(q, args.a, args.v))
        q_actual = wait_until_at_joint_target(
            rtde_receive,
            q,
            tolerance=args.tolerance,
            timeout=args.timeout,
        )

        print(f"Reached {name}. Max joint error: {max_joint_error(q_actual, q):.4f} rad")
        print_tcp_pose(rtde_receive)

        input("Confirm position, then press Enter for the next move.")

    rtde_receive.disconnect()
    print("\nDone.")


if __name__ == "__main__":
    main()
