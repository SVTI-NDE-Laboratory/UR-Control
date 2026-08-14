"""Robot movement helpers."""

import math
import time

from robot_connection import assert_robot_running, assert_robot_safe, send_script
from robot_scripts import movej_script, movel_pose_script, translate_tool_script


def max_joint_error(q_actual: list[float], q_target: list[float]) -> float:
    """Return the largest absolute joint error.

    Used as a simple completion criterion for movej targets.
    """

    return max(abs(actual - target) for actual, target in zip(q_actual, q_target))


def wait_until_at_joint_target(rtde_receive, q_target: list[float], tolerance: float, timeout: float) -> list[float]:
    """Wait until actual joints match the target within tolerance.

    Raises TimeoutError if the robot does not reach the target in time.
    """

    start = time.monotonic()

    while time.monotonic() - start < timeout:
        assert_robot_safe(rtde_receive)
        q_actual = rtde_receive.getActualQ()
        if max_joint_error(q_actual, q_target) <= tolerance:
            return q_actual
        time.sleep(0.1)

    assert_robot_safe(rtde_receive)
    q_actual = rtde_receive.getActualQ()
    error = max_joint_error(q_actual, q_target)
    raise TimeoutError(f"Target not reached within {timeout} s. Max joint error: {error:.4f} rad")


def vector_norm(values: list[float]) -> float:
    """Return the Euclidean norm of a numeric vector.

    Used to reduce TCP speed and TCP pose deltas to one scalar value.
    """

    return sum(value * value for value in values) ** 0.5


def wait_until_tcp_stops(rtde_receive, timeout: float, speed_tolerance: float = 0.002, settle_time: float = 0.5) -> None:
    """Wait until the TCP appears stopped.

    Safety state is checked on every poll so a stopped TCP is never mistaken
    for a successfully completed move after an emergency or protective stop.
    """

    time.sleep(0.2)
    start = time.monotonic()
    stopped_since = None

    while time.monotonic() - start < timeout:
        assert_robot_safe(rtde_receive)
        tcp_speed = rtde_receive.getActualTCPSpeed()
        speed = vector_norm(tcp_speed)

        if speed <= speed_tolerance:
            if stopped_since is None:
                stopped_since = time.monotonic()
            elif time.monotonic() - stopped_since >= settle_time:
                return
        else:
            stopped_since = None

        time.sleep(0.05)

    assert_robot_safe(rtde_receive)
    raise TimeoutError(f"TCP did not stop within {timeout} s.")


def wait_until_at_tcp_target(
    rtde_receive,
    target_pose: list[float],
    timeout: float,
    position_tolerance: float = 0.002,
    rotation_tolerance: float = 0.01,
) -> list[float]:
    """Wait until the TCP reaches a final Cartesian routine target."""

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        assert_robot_safe(rtde_receive)
        actual_pose = rtde_receive.getActualTCPPose()
        position_error = vector_norm(
            [actual_pose[index] - target_pose[index] for index in range(3)]
        )
        rotation_error = vector_norm(
            [actual_pose[index] - target_pose[index] for index in range(3, 6)]
        )
        if position_error <= position_tolerance and rotation_error <= rotation_tolerance:
            return actual_pose
        time.sleep(0.05)

    raise TimeoutError(f"TCP target not reached within {timeout} s.")


def print_tcp_pose(rtde_receive) -> None:
    """Print the current TCP pose from RTDE.

    Useful after a move for quick operator inspection.
    """

    x, y, z, rx, ry, rz = rtde_receive.getActualTCPPose()
    print(
        "Actual TCP pose: "
        f"x={x:.6f}, y={y:.6f}, z={z:.6f}, "
        f"rx={rx:.6f}, ry={ry:.6f}, rz={rz:.6f}"
    )


def joint_degrees(q: list[float]) -> str:
    """Format joint angles in degrees for human-readable logs.

    The robot still receives all joint values in radians.
    """

    return ", ".join(f"{math.degrees(value):.1f} deg" for value in q)


def movej(robot_ip: str, rtde_receive, q: list[float], a: float, v: float, tolerance: float, timeout: float) -> None:
    """Send one movej and wait until the target joints are reached.

    Python remains in control and only sends one movement at a time.
    """

    assert_robot_running(robot_ip)
    script = movej_script(q, a, v)
    send_script(robot_ip, script)
    wait_until_at_joint_target(rtde_receive, q, tolerance, timeout)


def translate_tool(robot_ip: str, rtde_receive, offset: list[float], a: float, v: float, timeout: float) -> None:
    """Translate the TCP by an offset in the tool frame and wait for completion.

    This is used for high/low motion and stepping along the measurement line.
    """

    script = translate_tool_script(offset, a, v)
    send_script(robot_ip, script)
    wait_until_tcp_stops(rtde_receive, timeout)


def movel_pose(robot_ip: str, rtde_receive, pose: list[float], a: float, v: float, timeout: float) -> None:
    """Move linearly to an absolute TCP pose and wait for completion.

    Use this for paths where a joint-space shortcut could hit something.
    """

    assert_robot_running(robot_ip)
    script = movel_pose_script(pose, a, v)
    send_script(robot_ip, script)
    wait_until_tcp_stops(rtde_receive, timeout)
