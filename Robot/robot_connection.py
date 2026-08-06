"""Small robot communication helpers."""

import socket


SCRIPT_PORT = 30002
DASHBOARD_PORT = 29999


def dashboard_command(robot_ip: str, command: str) -> str:
    """Send one command to the Dashboard server.

    Used for read-only preflight checks before any robot motion is sent.
    """

    with socket.create_connection((robot_ip, DASHBOARD_PORT), timeout=5) as sock:
        sock.recv(1024)
        sock.sendall((command + "\n").encode("utf-8"))
        return sock.recv(1024).decode("utf-8", errors="replace").strip()


def is_remote_control(robot_ip: str) -> bool:
    """Return whether the robot is in Remote Control mode.

    If this is false, scripts sent from Python will not execute as expected.
    """

    response = dashboard_command(robot_ip, "is in remote control").lower()
    return response.endswith("true")


def assert_remote_control(robot_ip: str) -> None:
    """Raise before motion if the robot is not in Remote Control mode.

    This catches the common case where the teach pendant is still in Manual mode.
    """

    if is_remote_control(robot_ip):
        return

    robot_mode = dashboard_command(robot_ip, "robotmode")
    safety_mode = dashboard_command(robot_ip, "safetymode")
    raise RuntimeError(
        "Robot is not in Remote Control mode. Switch the teach pendant from Manual/Local "
        "to Remote Control before running Python motion.\n"
        f"robotmode: {robot_mode}\n"
        f"safetymode: {safety_mode}"
    )


def send_script(robot_ip: str, script: str) -> None:
    """Send one URScript program to the robot.

    The robot executes the script immediately through port 30002.
    """

    if not script.endswith("\n"):
        script += "\n"

    with socket.create_connection((robot_ip, SCRIPT_PORT), timeout=5) as sock:
        sock.sendall(script.encode("utf-8"))


def get_rtde_receive(robot_ip: str, use_upper_range_registers: bool = False):
    """Create an RTDE receive connection.

    This is used to read actual joints, TCP pose, and program-running state.
    The default register range matches the older working RTDE examples.
    """

    try:
        from rtde_receive import RTDEReceiveInterface
    except ImportError as error:
        raise RuntimeError(
            "Install ur_rtde to wait for robot feedback:\n"
            "python -m pip install ur_rtde"
        ) from error

    return RTDEReceiveInterface(robot_ip, use_upper_range_registers=use_upper_range_registers)
