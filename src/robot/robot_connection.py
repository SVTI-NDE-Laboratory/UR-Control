"""Small robot communication helpers."""

import socket


SCRIPT_PORT = 30002
DASHBOARD_PORT = 29999

# RTDE safety_status_bits positions documented by Universal Robots/ur_rtde.
# Normal (bit 0) and reduced (bit 1) operation are not stop conditions.
SAFETY_STOP_BITS = {
    2: "protective stop",
    4: "safeguard stop",
    5: "system emergency stop",
    6: "robot emergency stop",
    7: "emergency stop",
    8: "safety violation",
    9: "safety fault",
    10: "stopped due to safety",
}


class RobotSafetyError(RuntimeError):
    """Raised when RTDE reports that robot motion was stopped by safety."""


class UnsafeStartPositionError(RuntimeError):
    """Raised when a run is requested while the robot is not at Home."""


def dashboard_command(robot_ip: str, command: str) -> str:
    """Send one command to the robot's Dashboard server."""

    with socket.create_connection((robot_ip, DASHBOARD_PORT), timeout=5) as sock:
        sock.recv(1024)
        sock.sendall((command + "\n").encode("utf-8"))
        return sock.recv(1024).decode("utf-8", errors="replace").strip()


def load_and_play_urp(robot_ip: str, program_path: str) -> None:
    """Load and play a controller-side URP program.

    ``program_path`` is the path as seen by the robot controller, for example
    ``Benoit/apply_force.urp``.
    """

    load_response = dashboard_command(robot_ip, f"load {program_path}")
    if not load_response.lower().startswith("loading program"):
        raise RuntimeError(f"Could not load URP '{program_path}': {load_response}")

    play_response = dashboard_command(robot_ip, "play")
    if "starting program" not in play_response.lower():
        raise RuntimeError(f"Could not start URP '{program_path}': {play_response}")


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


def assert_robot_running(robot_ip: str) -> None:
    """Require Remote Control mode and a powered, brake-released robot.

    ``RUNNING`` is the Dashboard robot mode in which the arm can accept motion.
    Remote Control by itself is insufficient: the controller can still report
    ``POWER_OFF``, ``IDLE``, or another non-motion state.
    """

    assert_remote_control(robot_ip)
    robot_mode = dashboard_command(robot_ip, "robotmode")
    if robot_mode.rsplit(":", 1)[-1].strip().upper() == "RUNNING":
        return

    safety_mode = dashboard_command(robot_ip, "safetymode")
    raise RuntimeError(
        "Robot is in Remote Control mode but is not ready for motion. "
        "Power on the robot and release its brakes before starting.\n"
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


def assert_robot_safe(rtde_receive) -> None:
    """Raise immediately when RTDE reports a safety-related stop."""

    status = rtde_receive.getSafetyStatusBits()
    active_conditions = [
        description
        for bit, description in SAFETY_STOP_BITS.items()
        if status & (1 << bit)
    ]
    if active_conditions:
        raise RobotSafetyError(
            "Robot motion stopped: " + ", ".join(active_conditions) + "."
        )


def assert_at_home(
    rtde_receive, home_q: list[float], joint_tolerance: float = 0.005
) -> None:
    """Require every actual joint to be close to the taught Home target.

    Home is joint-only in the active routine data, so this verifies the unique
    taught configuration rather than only the TCP position. No motion command
    is sent by this check.
    """

    assert_robot_safe(rtde_receive)
    actual_q = rtde_receive.getActualQ()
    if len(actual_q) != len(home_q):
        raise UnsafeStartPositionError(
            "Cannot verify Home: robot and Home joint vectors have different lengths."
        )

    joint_errors = [abs(actual - target) for actual, target in zip(actual_q, home_q)]
    maximum_error = max(joint_errors)
    if maximum_error > joint_tolerance:
        joint_number = joint_errors.index(maximum_error) + 1
        raise UnsafeStartPositionError(
            "Unsafe start prevented: robot is not at the taught Home position. "
            f"Joint {joint_number} differs by {maximum_error:.4f} rad; "
            f"allowed difference is {joint_tolerance:.4f} rad. "
            "Move the robot to Home before starting."
        )


def stop_robot(robot_ip: str, deceleration: float = 2.0) -> None:
    """Request a controlled stop for either a URScript move or a loaded URP.

    Sending ``stopj`` first interrupts a port-30002 motion with minimum delay.
    The following Dashboard ``stop`` covers a loaded PolyScope program such as
    the force measurement.
    Both are best-effort because a disconnected or emergency-stopped controller
    may reject commands precisely when cleanup is running.
    """

    stop_script = (
        "def python_external_stop():\n"
        f"  stopj({deceleration})\n"
        "end\n\n"
        "python_external_stop()\n"
    )
    errors = []
    try:
        send_script(robot_ip, stop_script)
    except (OSError, RuntimeError) as error:
        errors.append(error)

    try:
        dashboard_command(robot_ip, "stop")
    except (OSError, RuntimeError) as error:
        errors.append(error)

    if len(errors) == 2:
        raise RuntimeError(
            "Could not send a stop command to the robot: "
            + "; ".join(str(error) for error in errors)
        )


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
