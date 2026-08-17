"""Robot movement helpers."""

import math
import sys
import time

from robot_connection import (
    RobotSafetyError,
    assert_robot_running,
    assert_robot_safe,
    send_script,
    stop_robot,
)
from robot_scripts import movej_script, movel_pose_script


CARTESIAN_MOTION_START_TIMEOUT = 1.0
CARTESIAN_STALL_TIMEOUT = 1.5
CARTESIAN_POSITION_PROGRESS_THRESHOLD = 0.0002
CARTESIAN_ROTATION_PROGRESS_THRESHOLD = 0.002
JOINT_PROGRESS_THRESHOLD = 0.002
JOINT_SPEED_TOLERANCE = 0.01
JOINT_SETTLE_TIME = 0.2


def max_joint_error(q_actual: list[float], q_target: list[float]) -> float:
    """Return the largest absolute joint error.

    Used as a simple completion criterion for movej targets.
    """

    return max(abs(actual - target) for actual, target in zip(q_actual, q_target))


def wait_until_at_joint_target(
    rtde_receive,
    q_target: list[float],
    tolerance: float,
    timeout: float,
    watchdog: bool = True,
    motion_start_timeout: float = CARTESIAN_MOTION_START_TIMEOUT,
    stall_timeout: float = CARTESIAN_STALL_TIMEOUT,
    progress_threshold: float = JOINT_PROGRESS_THRESHOLD,
    require_target_progress: bool = True,
    speed_tolerance: float = JOINT_SPEED_TOLERANCE,
    settle_time: float = JOINT_SETTLE_TIME,
) -> list[float]:
    """Wait until actual joints match the target and have settled.

    Raises TimeoutError if the robot does not reach the target in time.
    """

    start = time.monotonic()
    progress_reference = None
    activity_reference = None
    motion_started = False
    last_progress = start
    settled_since = None

    while time.monotonic() - start < timeout:
        assert_robot_safe(rtde_receive)
        q_actual = rtde_receive.getActualQ()
        error = max_joint_error(q_actual, q_target)
        joint_speed = max(abs(value) for value in rtde_receive.getActualQd())
        at_target = error <= tolerance and joint_speed <= speed_tolerance
        if at_target:
            if settled_since is None:
                settled_since = time.monotonic()
            elif time.monotonic() - settled_since >= settle_time:
                return q_actual
        else:
            settled_since = None
        now = time.monotonic()
        if progress_reference is None:
            progress_reference = error
            activity_reference = list(q_actual)
        target_progress = progress_reference - error >= progress_threshold
        joint_activity = (
            max_joint_error(q_actual, activity_reference) >= progress_threshold
        )
        made_progress = target_progress if require_target_progress else joint_activity
        if made_progress:
            progress_reference = error
            activity_reference = list(q_actual)
            motion_started = True
            last_progress = now
        if watchdog and not at_target and not motion_started and now - start >= motion_start_timeout:
            raise TimeoutError(
                f"Joint motion did not start within {motion_start_timeout:.1f} s "
                f"(maximum joint error {error:.6f} rad, maximum joint speed "
                f"{joint_speed:.6f} rad/s)."
            )
        if watchdog and not at_target and motion_started and now - last_progress >= stall_timeout:
            raise TimeoutError(
                f"Joint motion stopped making progress for {stall_timeout:.1f} s "
                f"(maximum joint error {error:.6f} rad, maximum joint speed "
                f"{joint_speed:.6f} rad/s)."
            )
        time.sleep(0.05)

    assert_robot_safe(rtde_receive)
    q_actual = rtde_receive.getActualQ()
    error = max_joint_error(q_actual, q_target)
    joint_speed = max(abs(value) for value in rtde_receive.getActualQd())
    raise TimeoutError(
        f"Joint target not reached and settled within {timeout} s "
        f"(maximum joint error {error:.6f} rad, maximum joint speed "
        f"{joint_speed:.6f} rad/s)."
    )


def vector_norm(values: list[float]) -> float:
    """Return the Euclidean norm of a numeric vector.

    Used to reduce TCP speed and TCP pose deltas to one scalar value.
    """

    return sum(value * value for value in values) ** 0.5


def tcp_target_errors(
    actual_pose: list[float], target_pose: list[float]
) -> tuple[float, float]:
    """Return Cartesian position and rotation-vector target errors."""

    position_error = vector_norm(
        [actual_pose[index] - target_pose[index] for index in range(3)]
    )
    rotation_error = vector_norm(
        [actual_pose[index] - target_pose[index] for index in range(3, 6)]
    )
    return position_error, rotation_error


def _tcp_target_reached(
    position_error: float,
    rotation_error: float,
    tcp_speed: float,
    position_tolerance: float,
    rotation_tolerance: float,
    speed_tolerance: float,
) -> bool:
    """Return whether the TCP is at a target and slow enough to be settled."""

    return (
        position_error <= position_tolerance
        and rotation_error <= rotation_tolerance
        and tcp_speed <= speed_tolerance
    )


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
    position_tolerance: float = 0.001,
    rotation_tolerance: float = 0.01,
    speed_tolerance: float = 0.002,
    settle_time: float = 0.2,
    motion_start_timeout: float = CARTESIAN_MOTION_START_TIMEOUT,
    stall_timeout: float = CARTESIAN_STALL_TIMEOUT,
    position_progress_threshold: float = CARTESIAN_POSITION_PROGRESS_THRESHOLD,
    rotation_progress_threshold: float = CARTESIAN_ROTATION_PROGRESS_THRESHOLD,
    watchdog: bool = True,
    require_target_progress: bool = True,
) -> list[float]:
    """Wait for a Cartesian target, failing early if motion never progresses."""

    start = time.monotonic()
    settled_since = None
    motion_started = False
    last_activity = start
    progress_position_reference = None
    progress_rotation_reference = None
    activity_pose_reference = None
    while time.monotonic() - start < timeout:
        assert_robot_safe(rtde_receive)
        actual_pose = rtde_receive.getActualTCPPose()
        position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)
        tcp_speed = vector_norm(rtde_receive.getActualTCPSpeed())
        now = time.monotonic()

        if progress_position_reference is None:
            progress_position_reference = position_error
            progress_rotation_reference = rotation_error
            activity_pose_reference = list(actual_pose)

        target_progress = (
            progress_position_reference - position_error
            >= position_progress_threshold
            or progress_rotation_reference - rotation_error
            >= rotation_progress_threshold
        )
        activity_position, activity_rotation = tcp_target_errors(
            actual_pose, activity_pose_reference
        )
        pose_activity = (
            activity_position >= position_progress_threshold
            or activity_rotation >= rotation_progress_threshold
        )
        made_progress = target_progress if require_target_progress else pose_activity
        if made_progress:
            progress_position_reference = position_error
            progress_rotation_reference = rotation_error
            activity_pose_reference = list(actual_pose)
        if made_progress:
            motion_started = True
            last_activity = now

        at_target = _tcp_target_reached(
            position_error,
            rotation_error,
            tcp_speed,
            position_tolerance,
            rotation_tolerance,
            speed_tolerance,
        )
        if at_target:
            if settled_since is None:
                settled_since = time.monotonic()
            elif time.monotonic() - settled_since >= settle_time:
                return actual_pose
        else:
            settled_since = None

        elapsed = now - start
        if watchdog and not at_target and not motion_started and elapsed >= motion_start_timeout:
            raise TimeoutError(
                f"Cartesian motion did not start within {motion_start_timeout:.1f} s "
                f"(position error {position_error:.6f} m, rotation-vector error "
                f"{rotation_error:.6f} rad, TCP speed {tcp_speed:.6f})."
            )
        if (
            watchdog
            and not at_target
            and motion_started
            and now - last_activity >= stall_timeout
        ):
            raise TimeoutError(
                f"Cartesian motion stopped making progress for {stall_timeout:.1f} s "
                f"before reaching its target (position error {position_error:.6f} m, "
                f"rotation-vector error {rotation_error:.6f} rad, TCP speed "
                f"{tcp_speed:.6f})."
            )
        time.sleep(0.05)

    assert_robot_safe(rtde_receive)
    actual_pose = rtde_receive.getActualTCPPose()
    position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)
    raise TimeoutError(
        f"TCP target not reached and settled within {timeout} s "
        f"(position error {position_error:.6f} m, rotation-vector error "
        f"{rotation_error:.6f} rad)."
    )


def ensure_at_tcp_target(
    robot_ip: str,
    rtde_receive,
    target_pose: list[float],
    acceleration: float,
    speed: float,
    timeout: float,
    position_tolerance: float = 0.001,
    rotation_tolerance: float = 0.01,
    speed_tolerance: float = 0.002,
) -> list[float]:
    """Verify a measurement pose and correct it before work starts there."""

    assert_robot_safe(rtde_receive)
    actual_pose = rtde_receive.getActualTCPPose()
    position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)
    actual_speed = vector_norm(rtde_receive.getActualTCPSpeed())
    if _tcp_target_reached(
        position_error,
        rotation_error,
        actual_speed,
        position_tolerance,
        rotation_tolerance,
        speed_tolerance,
    ):
        return actual_pose

    print(
        "Measurement target verification failed; correcting pose before force "
        f"application (position error {position_error:.6f} m, "
        f"rotation-vector error {rotation_error:.6f} rad)."
    )
    movel_pose(
        robot_ip,
        rtde_receive,
        target_pose,
        acceleration,
        speed,
        timeout,
    )
    return rtde_receive.getActualTCPPose()


def rotate_vector(rotation_vector: list[float], vector: list[float]) -> list[float]:
    """Rotate a vector using a UR axis-angle rotation vector."""

    angle = vector_norm(rotation_vector)
    if angle <= 1e-12:
        return list(vector)

    axis = [value / angle for value in rotation_vector]
    cosine = math.cos(angle)
    sine = math.sin(angle)
    dot = sum(axis[index] * vector[index] for index in range(3))
    cross = [
        axis[1] * vector[2] - axis[2] * vector[1],
        axis[2] * vector[0] - axis[0] * vector[2],
        axis[0] * vector[1] - axis[1] * vector[0],
    ]
    return [
        vector[index] * cosine
        + cross[index] * sine
        + axis[index] * dot * (1.0 - cosine)
        for index in range(3)
    ]


def translated_tool_target(start_pose: list[float], offset: list[float]) -> list[float]:
    """Return the base-frame TCP target for a local tool-frame translation."""

    if len(start_pose) != 6 or len(offset) != 3:
        raise ValueError("A TCP pose needs six values and a translation needs three.")
    base_offset = rotate_vector(start_pose[3:6], offset)
    return [
        start_pose[index] + base_offset[index] for index in range(3)
    ] + list(start_pose[3:6])


def execute_verified_movel(
    robot_ip: str,
    rtde_receive,
    script_factory,
    target_pose: list[float],
    timeout: float,
    max_attempts: int = 3,
) -> list[float]:
    """Send a linear move and retry only when its target is not reached."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    assert_robot_safe(rtde_receive)
    actual_pose = rtde_receive.getActualTCPPose()
    position_error, rotation_error = tcp_target_errors(actual_pose, target_pose)
    tcp_speed = vector_norm(rtde_receive.getActualTCPSpeed())
    if _tcp_target_reached(
        position_error,
        rotation_error,
        tcp_speed,
        0.001,
        0.01,
        0.002,
    ):
        return actual_pose

    for attempt in range(1, max_attempts + 1):
        assert_robot_running(robot_ip)
        send_script(robot_ip, script_factory())
        try:
            return wait_until_at_tcp_target(
                rtde_receive,
                target_pose,
                timeout,
            )
        except TimeoutError as error:
            stop_error = None
            try:
                stop_robot(robot_ip)
                wait_until_tcp_stops(
                    rtde_receive,
                    timeout=2.0,
                    speed_tolerance=0.002,
                    settle_time=0.2,
                )
            except RobotSafetyError:
                raise
            except Exception as caught_stop_error:
                stop_error = caught_stop_error

            if stop_error is not None:
                raise RuntimeError(
                    "Cartesian move failed and a clean stop could not be "
                    f"confirmed; refusing to retry. Move error: {error}. "
                    f"Stop error: {stop_error}"
                ) from error

            if attempt == max_attempts:
                raise TimeoutError(
                    f"Cartesian move failed after {max_attempts} attempts. "
                    f"{error}"
                ) from error

            print(
                f"Warning: Cartesian target was not reached on attempt "
                f"{attempt}/{max_attempts}; stopped and retrying. {error}",
                file=sys.stderr,
            )

    raise AssertionError("Unreachable Cartesian retry state.")


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


def movej(
    robot_ip: str,
    rtde_receive,
    q: list[float],
    a: float,
    v: float,
    tolerance: float,
    timeout: float,
    max_attempts: int = 3,
) -> None:
    """Send one movej and wait until the target joints are reached.

    Python remains in control and only sends one movement at a time.
    """

    assert_robot_safe(rtde_receive)
    initial_error = max_joint_error(rtde_receive.getActualQ(), q)
    initial_speed = max(abs(value) for value in rtde_receive.getActualQd())
    if initial_error <= tolerance and initial_speed <= JOINT_SPEED_TOLERANCE:
        return

    for attempt in range(1, max_attempts + 1):
        assert_robot_running(robot_ip)
        send_script(robot_ip, movej_script(q, a, v))
        try:
            wait_until_at_joint_target(rtde_receive, q, tolerance, timeout)
            return
        except TimeoutError as error:
            try:
                stop_robot(robot_ip)
                wait_until_tcp_stops(
                    rtde_receive,
                    timeout=2.0,
                    speed_tolerance=0.002,
                    settle_time=0.2,
                )
            except RobotSafetyError:
                raise
            except Exception as stop_error:
                raise RuntimeError(
                    "Joint move failed and a clean stop could not be confirmed; "
                    f"refusing to retry. Move error: {error}. Stop error: {stop_error}"
                ) from error

            if attempt == max_attempts:
                raise TimeoutError(
                    f"Joint move failed after {max_attempts} attempts. {error}"
                ) from error
            print(
                f"Warning: joint target was not reached on attempt "
                f"{attempt}/{max_attempts}; stopped and retrying. {error}",
                file=sys.stderr,
            )


def translate_tool(robot_ip: str, rtde_receive, offset: list[float], a: float, v: float, timeout: float) -> None:
    """Translate the TCP by an offset in the tool frame and wait for completion.

    This is used for high/low motion and stepping along the measurement line.
    """

    start_pose = rtde_receive.getActualTCPPose()
    target_pose = translated_tool_target(start_pose, offset)
    execute_verified_movel(
        robot_ip,
        rtde_receive,
        # Use one absolute target for every retry. Reapplying a relative offset
        # after a partially completed first attempt could otherwise overshoot.
        lambda: movel_pose_script(target_pose, a, v),
        target_pose,
        timeout,
    )


def movel_pose(robot_ip: str, rtde_receive, pose: list[float], a: float, v: float, timeout: float) -> None:
    """Move linearly to an absolute TCP pose and wait for completion.

    Use this for paths where a joint-space shortcut could hit something.
    """

    execute_verified_movel(
        robot_ip,
        rtde_receive,
        lambda: movel_pose_script(pose, a, v),
        pose,
        timeout,
    )
