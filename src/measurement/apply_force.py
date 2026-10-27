"""Configure and run one robot-side force application cycle."""

import sys
import math
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from rtde_io import RTDEIOInterface
from rtde_receive import RTDEReceiveInterface


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import (
    assert_robot_running,
    assert_robot_safe,
    load_and_play_urp,
    stop_robot,
)
from line_planner import millimetres_to_metres
from robot_move import ensure_at_tcp_target, tcp_target_errors


STATUS_POLL_INTERVAL = 0.01
INITIALIZATION_TIMEOUT = 5.0
# The URP owns the actual 10-second approach limit. This receive-side deadline
# includes a small margin so Python cannot time out just before status arrives.
APPROACH_STATUS_TIMEOUT = 15.0
SIMULATION_STATUS_TIMEOUT = 7.0
# Match approach_speed in apply_force_simulation.script.
SIMULATION_APPROACH_SPEED_MM_S = 5.0
RETURN_TIMEOUT = 30.0
RETURN_ACCELERATION = 100.0
RETURN_SPEED = 20.0
FORCE_MOTION_START_TIMEOUT = 2.0
FORCE_MOTION_STALL_TIMEOUT = 2.0
FORCE_POSITION_PROGRESS_THRESHOLD = 0.00005
FORCE_ROTATION_PROGRESS_THRESHOLD = 0.001
# Passive simulation verification: no Python motion commands are issued.
SIMULATION_RETURN_VERIFY_TIMEOUT = 2.0
SIMULATION_RETURN_SETTLE_TIME = 0.2
SIMULATION_RETURN_POSITION_TOLERANCE = 0.001  # m
SIMULATION_RETURN_ROTATION_TOLERANCE = 0.01  # rad
SIMULATION_RETURN_LINEAR_SPEED_TOLERANCE = 0.002  # m/s
SIMULATION_RETURN_ANGULAR_SPEED_TOLERANCE = 0.01  # rad/s


def force_contact_log_prefix(
    simulation: bool,
    acquisition_context: dict | None,
) -> str:
    """Return the standard operator prefix for force-contact log lines."""

    context = acquisition_context or {}
    simulation_text = "SIMU " if simulation else ""
    measurement_index = context.get("measurement_index", "?")
    x_coordinate = context.get("x_coordinate", context.get("line_position"))
    if x_coordinate is None:
        x_text = "X+offset=n/a"
    else:
        x_text = f"X+offset={float(x_coordinate):.3f} mm"
    return f"{simulation_text}Point {measurement_index} {x_text}: "


def print_force_contact_log(
    message: str,
    simulation: bool,
    acquisition_context: dict | None,
) -> None:
    """Print one standardized force-contact status line."""

    print(f"{force_contact_log_prefix(simulation, acquisition_context)}{message}")


def acquisition_control_label(acquisition_context: dict | None) -> str:
    """Return the operator-facing name for the force-hold release controller."""

    return str((acquisition_context or {}).get("acquisition_label", "client"))


def wait_for_status(
    rtde_receive,
    accepted_statuses: set[int],
    timeout: float,
    phase: str,
    motion_watchdog: bool = False,
) -> int:
    """Wait for one force-program status, with safety checks and a deadline."""

    start = time.monotonic()
    deadline = start + timeout
    last_status = rtde_receive.getOutputIntRegister(42)
    activity_pose = rtde_receive.getActualTCPPose() if motion_watchdog else None
    motion_started = False
    last_progress = start
    while True:
        assert_robot_safe(rtde_receive)
        last_status = rtde_receive.getOutputIntRegister(42)
        if last_status == 4:
            raise ValueError("Force program rejected its settings (status 4).")
        if last_status == 5:
            raise RuntimeError("Simulation stopped at its 40 N force guard (status 5); automatic return disabled.")
        if last_status == 6:
            raise TimeoutError("Simulation motion timed out (status 6); automatic return disabled.")
        if last_status in accepted_statuses:
            return last_status
        now = time.monotonic()
        if motion_watchdog:
            actual_pose = rtde_receive.getActualTCPPose()
            position_change, rotation_change = tcp_target_errors(
                actual_pose, activity_pose
            )
            made_progress = (
                position_change >= FORCE_POSITION_PROGRESS_THRESHOLD
                or rotation_change >= FORCE_ROTATION_PROGRESS_THRESHOLD
            )
            if made_progress:
                activity_pose = list(actual_pose)
                motion_started = True
                last_progress = now
            if (
                not motion_started
                and now - start >= FORCE_MOTION_START_TIMEOUT
            ):
                raise TimeoutError(
                    f"Force program motion did not start during {phase} within "
                    f"{FORCE_MOTION_START_TIMEOUT:.1f} s; last status was "
                    f"{last_status}."
                )
            if (
                motion_started
                and now - last_progress >= FORCE_MOTION_STALL_TIMEOUT
            ):
                raise TimeoutError(
                    f"Force program motion stopped progressing during {phase} "
                    f"for {FORCE_MOTION_STALL_TIMEOUT:.1f} s; last status was "
                    f"{last_status}."
                )
        if now >= deadline:
            raise TimeoutError(
                f"Force program timed out during {phase} after {timeout:.1f} s; "
                f"last status was {last_status}."
            )
        time.sleep(STATUS_POLL_INTERVAL)


def verify_simulation_return(rtde_receive, target_pose: list[float]) -> list[float]:
    """Observe a stable returned pose after URP completion without correcting it."""
    deadline = time.monotonic() + SIMULATION_RETURN_VERIFY_TIMEOUT
    stable_since = None
    while True:
        assert_robot_safe(rtde_receive)
        returned_pose = rtde_receive.getActualTCPPose()
        speed = rtde_receive.getActualTCPSpeed()
        if len(returned_pose) != 6 or len(speed) != 6 or not all(math.isfinite(value) for value in [*returned_pose, *speed]):
            raise RuntimeError("Simulation return verification failed: invalid TCP feedback; automatic correction disabled.")

        position_error, rotation_error = tcp_target_errors(returned_pose, target_pose)
        linear_speed = math.sqrt(sum(value * value for value in speed[:3]))
        angular_speed = math.sqrt(sum(value * value for value in speed[3:]))
        within_limits = (position_error <= SIMULATION_RETURN_POSITION_TOLERANCE
            and rotation_error <= SIMULATION_RETURN_ROTATION_TOLERANCE
            and linear_speed <= SIMULATION_RETURN_LINEAR_SPEED_TOLERANCE
            and angular_speed <= SIMULATION_RETURN_ANGULAR_SPEED_TOLERANCE)
        now = time.monotonic()

        # Completion status and pose/speed samples can arrive at different times.
        # Require consecutive in-tolerance feedback rather than one sample.
        if within_limits:
            if stable_since is None:
                stable_since = now
            if now - stable_since >= SIMULATION_RETURN_SETTLE_TIME:
                return returned_pose
        else:
            stable_since = None

        if now >= deadline:
            raise RuntimeError(
                "Simulation return verification failed after "
                f"{SIMULATION_RETURN_VERIFY_TIMEOUT:g} s: "
                f"position error {position_error * 1000:.3f} mm "
                f"(limit {SIMULATION_RETURN_POSITION_TOLERANCE * 1000:g} mm), "
                f"rotation error {rotation_error:.6f} rad "
                f"(limit {SIMULATION_RETURN_ROTATION_TOLERANCE:g} rad), "
                f"linear speed {linear_speed * 1000:.3f} mm/s "
                f"(limit {SIMULATION_RETURN_LINEAR_SPEED_TOLERANCE * 1000:g} mm/s), "
                f"angular speed {angular_speed:.6f} rad/s "
                f"(limit {SIMULATION_RETURN_ANGULAR_SPEED_TOLERANCE:g} rad/s); "
                "automatic correction disabled."
            )
        time.sleep(STATUS_POLL_INTERVAL)


def apply_force(robot_ip: str, program_path: str, max_distance: float, target_force: float,
                simulation: bool = False, acquire_data: Callable[[dict], dict] | None = None,
                acquisition_context: dict | None = None, stop_method: str = "timer",
                on_force_success: Callable[[str], None] | None = None, hold_duration: float = 0.5,
                settling_time: float = 1.5, simulation_program_path: str | None = None) -> tuple[bool, str]:
    """Run a force cycle and return its result plus measurement timestamp.

    ``max_distance`` is configured in millimetres. It is converted to metres
    only when written to the robot input register. ``settling_time`` is in
    seconds. Simulation selects its own guarded travel URP; both programs signal
    readiness after settling and wait for the same Python release.
    """

    # Input doubles: 43 distance [m], 44 settling [s], 45 target [N].
    # Input/output integer 42 carries the measurement-release handshake.
    status_register = 42
    max_distance_register, settling_time_register, target_force_register = 43, 44, 45

    # Validate values before connecting.
    from measurement_config import measurement_stop_method
    stop_method = measurement_stop_method({"measurement": {"stop_method": stop_method}})
    if stop_method == "client_feedback" and acquire_data is None:
        raise ValueError("client_feedback requires an acquisition callback to release the hold.")
    if isinstance(hold_duration, bool) or not isinstance(hold_duration, (int, float)) or not math.isfinite(hold_duration) or hold_duration <= 0:
        raise ValueError("hold_duration must be positive and finite (seconds).")
    for name, value in (("target_force", target_force), ("max_distance", max_distance)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite.")
    if isinstance(settling_time, bool) or not isinstance(settling_time, (int, float)) or not math.isfinite(settling_time) or settling_time < 0:
        raise ValueError("settling_time must be nonnegative and finite (seconds).")
    if not isinstance(simulation, bool):
        raise ValueError("simulation must be true or false.")
    selected_program = simulation_program_path if simulation else program_path
    if not isinstance(selected_program, str) or not selected_program.strip():
        raise ValueError("Specify a simulation_program_path for simulation and program_path for real force.")

    # Remote Control is not enough: the arm must also be powered and brake-released.
    assert_robot_running(robot_ip)

    # IO writes robot inputs; Receive reads robot status.
    rtde_io = RTDEIOInterface(robot_ip, use_upper_range_registers=True)
    rtde_receive = RTDEReceiveInterface(
        robot_ip,
        variables=[
            "timestamp",
            "actual_TCP_pose",
            "actual_TCP_speed",
            "output_int_register_42",
            "safety_status_bits",
        ],
        use_upper_range_registers=True,
    )

    try:
        # Capture the exact pose before the force program can move. The URP
        # independently captures the same starting pose for its return move.
        assert_robot_safe(rtde_receive)
        pre_force_pose = rtde_receive.getActualTCPPose()

        # Send physical values before starting the URP.
        parameters = {
            max_distance_register: millimetres_to_metres(max_distance),
            settling_time_register: settling_time,
            target_force_register: target_force,
        }

        for register, value in parameters.items():
            if not rtde_io.setInputDoubleRegister(register, value):
                raise RuntimeError(f"Could not write input double register {register}.")

        # Clear any previous hold acknowledgement.
        if not rtde_io.setInputIntRegister(status_register, 0): raise RuntimeError(f"Could not reset input integer register {status_register}.")

        # Start the robot-side force sequence.
        print_force_contact_log(
            "The cobot starts its procedure to apply force.", simulation, acquisition_context,
        )
        load_and_play_urp(robot_ip, selected_program)

        # Wait for the URP to clear any stale status.
        print("Force program: waiting for initialization.")
        wait_for_status(
            rtde_receive,
            {0},
            INITIALIZATION_TIMEOUT,
            "initialization",
        )

        # Status 1 means real or simulated force success.
        force_reached = False

        # Wait for success (1), distance/approach limit (2), or hold timeout (3).
        print("Force program: waiting for target, settling, distance limit, or timeout.")
        status = wait_for_status(
            rtde_receive,
            {1, 2, 3},
            (max_distance / SIMULATION_APPROACH_SPEED_MM_S + SIMULATION_STATUS_TIMEOUT
             if simulation else APPROACH_STATUS_TIMEOUT) + settling_time,
            "force approach and settling",
            # Settling waits in place; the URP bounds approach motion.
            motion_watchdog=False,
        )
        measurement_timestamp = (
            datetime.now().astimezone().isoformat(timespec="milliseconds")
        )

        if status == 1:
            force_reached = True
            if on_force_success is not None:
                on_force_success(measurement_timestamp)
            print_force_contact_log(
                "The cobot is ready for measurement (settling completed).",
                simulation, acquisition_context,
            )
            if stop_method == "client_feedback":
                acquisition_result = acquire_data(dict(acquisition_context or {}))
                if acquisition_result.get("completed_at"):
                    measurement_timestamp = str(acquisition_result["completed_at"])
            else:
                # Timer starts only after real/simulated force success. Check
                # safety and the hold status throughout; never time the URScript.
                hold_deadline = time.monotonic() + hold_duration
                while True:
                    assert_robot_safe(rtde_receive)
                    current_status = rtde_receive.getOutputIntRegister(status_register)
                    if current_status != 1:
                        raise TimeoutError(
                            f"Force hold ended before the Python timer completed; robot status is {current_status}."
                        )
                    remaining = hold_deadline - time.monotonic()
                    if remaining <= 1e-9:
                        break
                    time.sleep(min(0.05, remaining))

            # Both timer and client completion use the same release handshake.
            assert_robot_safe(rtde_receive)
            current_status = rtde_receive.getOutputIntRegister(status_register)
            if current_status != 1:
                raise TimeoutError(
                    "Force hold ended before acknowledgement could be sent; "
                    f"robot status is {current_status}."
                )
            if not rtde_io.setInputIntRegister(status_register, 1):
                raise RuntimeError("Could not send return acknowledgement.")
            print("Force program: acquisition acknowledged; releasing force hold.")
        elif status == 3:
            raise TimeoutError("Robot timed out while waiting for acknowledgement.")

        # Status 1 covers acquisition AND return; it does not mark the start of
        # return motion. A controller may take time to release force, and
        # simulation/contact at the initial pose may need no return
        # displacement. Require bounded program completion, not visible motion.
        print("Force program: waiting for return to the measurement pose.")
        return_status = wait_for_status(
            rtde_receive,
            {0, 3},
            max(RETURN_TIMEOUT, max_distance / RETURN_SPEED + SIMULATION_STATUS_TIMEOUT)
            if simulation else RETURN_TIMEOUT,
            "return to the measurement pose",
        )
        if return_status == 3:
            raise TimeoutError("Robot timed out while waiting for acknowledgement.")
        print("Force program: verifying the pre-force pose.")
        if simulation:
            # Simulation motion stays inside the guarded URP. Do not issue an
            # unguarded corrective move if its reported return is inaccurate.
            returned_pose = verify_simulation_return(rtde_receive, pre_force_pose)
        else:
            returned_pose = ensure_at_tcp_target(
                robot_ip,
                rtde_receive,
                pre_force_pose,
                millimetres_to_metres(RETURN_ACCELERATION),
                millimetres_to_metres(RETURN_SPEED),
                RETURN_TIMEOUT,
            )
        position_error, rotation_error = tcp_target_errors(
            returned_pose, pre_force_pose
        )
        print(
            "Force program: return verified "
            f"(position error {position_error * 1000:.3f} mm, "
            f"rotation error {rotation_error:.6f} rad)."
        )

        return force_reached, measurement_timestamp
    except BaseException:
        # A stalled force program may still own force mode or a return move.
        # Stop it before propagating the error to the measurement coordinator.
        try:
            stop_robot(robot_ip)
        except Exception as stop_error:
            print(
                f"Warning: force-program stop command failed: {stop_error}",
                file=sys.stderr,
            )
        raise
    finally:
        # Reset Python-owned inputs and close both connections.
        rtde_io.setInputIntRegister(status_register, 0)
        rtde_receive.disconnect()
        rtde_io.disconnect()


if __name__ == "__main__":
    input("Press Enter to load the URP and start, or Ctrl+C to cancel.")

    force_reached, measurement_timestamp = apply_force(
        "192.168.3.10",
        "/Projects/BAM TTS/Programs/Apply_Force/apply_force.urp",
        50.0,
        200.0,
        simulation=False,
    )
    print(f"force_reached = {force_reached}, timestamp = {measurement_timestamp}")
