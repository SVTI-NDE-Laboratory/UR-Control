"""Configure and run one robot-side force application cycle."""

import sys
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
RETURN_TIMEOUT = 30.0
RETURN_ACCELERATION = 100.0
RETURN_SPEED = 20.0
FORCE_MOTION_START_TIMEOUT = 2.0
FORCE_MOTION_STALL_TIMEOUT = 2.0
FORCE_POSITION_PROGRESS_THRESHOLD = 0.00005
FORCE_ROTATION_PROGRESS_THRESHOLD = 0.001


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


def effective_simulation_mode(
    contact_threshold: float, holding_force: float, simulation: bool = False
) -> bool:
    """Validate force values and enable simulation for the zero/zero pair."""

    if contact_threshold < 0 or holding_force < 0:
        raise ValueError("contact_threshold and holding_force cannot be negative.")
    if (contact_threshold == 0) != (holding_force == 0):
        raise ValueError(
            "contact_threshold and holding_force must either both be zero "
            "for simulation or both be positive."
        )
    if holding_force < contact_threshold:
        raise ValueError("holding_force must be at least contact_threshold.")
    return simulation or (contact_threshold == 0 and holding_force == 0)


def apply_force(
    robot_ip: str,
    program_path: str,
    max_distance: float,
    contact_threshold: float,
    holding_force: float,
    simulation: bool = False,
    acquire_data: Callable[[dict], dict] | None = None,
    acquisition_context: dict | None = None,
    acknowledge_force_hold: bool = True,
) -> tuple[bool, str]:
    """Run a force cycle and return its result plus measurement timestamp.

    ``max_distance`` is configured in millimetres. It is converted to metres
    only when written to the robot input register.
    """

    # Integer registers: status/ack 42 and simulation 46.
    # Double registers: max distance 43, contact threshold 44, holding force 45.
    # Force-program motion values remain hardcoded in the controller-side URP.
    status_register = 42
    max_distance_register, contact_threshold_register = 43, 44
    holding_force_register = 45
    simulation_register = 46

    # Retain a bounded standalone fallback for examples that do not launch the
    # acquisition server. Main supplies ``acquire_data`` instead.
    fallback_hold_duration = 3.0

    # Validate values before connecting.
    if max_distance <= 0: raise ValueError("max_distance must be positive.")
    simulation = effective_simulation_mode(
        contact_threshold, holding_force, simulation
    )

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
            contact_threshold_register: contact_threshold,
            holding_force_register: holding_force,
        }

        for register, value in parameters.items():
            if not rtde_io.setInputDoubleRegister(register, value):
                raise RuntimeError(f"Could not write input double register {register}.")

        # Always overwrite simulation so an earlier True cannot persist.
        simulation_value = 1 if simulation else 0
        if not rtde_io.setInputIntRegister(simulation_register, simulation_value): raise RuntimeError(f"Could not write simulation register {simulation_register}.")

        # Clear any previous hold acknowledgement.
        if not rtde_io.setInputIntRegister(status_register, 0): raise RuntimeError(f"Could not reset input integer register {status_register}.")

        # Start the robot-side force sequence.
        load_and_play_urp(robot_ip, program_path)

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
        print("Force program: waiting for contact, distance limit, or timeout.")
        status = wait_for_status(
            rtde_receive,
            {1, 2, 3},
            SIMULATION_STATUS_TIMEOUT if simulation else APPROACH_STATUS_TIMEOUT,
            "force approach",
            # A simulation is allowed to remain stationary until its two-second
            # controller-side timeout reports success.
            motion_watchdog=not simulation,
        )
        measurement_timestamp = (
            datetime.now().astimezone().isoformat(timespec="milliseconds")
        )

        if status == 1:
            force_reached = True
            if acquire_data is not None:
                print("Data acquisition: requesting measurement.")
                acquisition_result = acquire_data(dict(acquisition_context or {}))
                completed_at = acquisition_result.get("completed_at")
                if completed_at:
                    measurement_timestamp = str(completed_at)
                acquisition_time = acquisition_result.get("acquisition_time")
                duration_text = (
                    f" in {float(acquisition_time):.3f} s"
                    if acquisition_time is not None
                    else ""
                )
                print(f"Data acquisition: measurement completed{duration_text}.")
            elif acknowledge_force_hold:
                print(
                    "Data acquisition callback unavailable; using standalone "
                    f"{fallback_hold_duration:.1f} s hold."
                )
                hold_deadline = time.monotonic() + fallback_hold_duration
                while True:
                    remaining = hold_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    assert_robot_safe(rtde_receive)
                    time.sleep(min(0.05, remaining))
            else:
                print(
                    "Data acquisition server disabled; robot program owns "
                    "acquisition and return."
                )

            if acknowledge_force_hold:
                # Do not acknowledge a controller that has already left its hold
                # because its own acknowledgement deadline expired.
                assert_robot_safe(rtde_receive)
                current_status = rtde_receive.getOutputIntRegister(status_register)
                if current_status != 1:
                    raise TimeoutError(
                        "Force hold ended before data acquisition acknowledgement "
                        f"could be sent; robot status is {current_status}."
                    )
                if not rtde_io.setInputIntRegister(status_register, 1):
                    raise RuntimeError("Could not send return acknowledgement.")
                print("Force program: acquisition acknowledged; releasing force hold.")
        elif status == 3:
            raise TimeoutError("Robot timed out while waiting for acknowledgement.")

        # Wait until the robot has returned to its initial pose.
        print("Force program: waiting for return to the measurement pose.")
        wait_for_status(
            rtde_receive,
            {0},
            RETURN_TIMEOUT,
            "return to the measurement pose",
            motion_watchdog=True,
        )
        print("Force program: verifying the pre-force pose.")
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
            f"rotation-vector error {rotation_error:.6f} rad)."
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
        rtde_io.setInputIntRegister(simulation_register, 0)
        rtde_receive.disconnect()
        rtde_io.disconnect()


if __name__ == "__main__":
    input("Press Enter to load the URP and start, or Ctrl+C to cancel.")

    force_reached, measurement_timestamp = apply_force(
        "192.168.3.10",
        "Benoit/apply_force.urp",
        50.0,
        15.0,
        20.0,
        simulation=False,
    )
    print(f"force_reached = {force_reached}, timestamp = {measurement_timestamp}")
