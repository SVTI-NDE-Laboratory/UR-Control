"""Configure and run one robot-side force application cycle."""

import sys
import time
from pathlib import Path

from rtde_io import RTDEIOInterface
from rtde_receive import RTDEReceiveInterface


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "src" / "robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import assert_robot_running, assert_robot_safe, load_and_play_urp


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
) -> bool:
    """Run a force cycle and block until the robot returns; simulation can report maximum distance as success."""

    # Integer registers: status/ack 42 and simulation 46.
    # Double registers: max distance 43, contact threshold 44, holding force 45.
    # Force-program motion values remain hardcoded in the controller-side URP.
    status_register = 42
    max_distance_register, contact_threshold_register = 43, 44
    holding_force_register = 45
    simulation_register = 46

    # Python ends the hold after this fixed measurement period.
    hold_duration = 3.0

    # Validate values before connecting.
    if max_distance <= 0: raise ValueError("max_distance must be positive.")
    simulation = effective_simulation_mode(
        contact_threshold, holding_force, simulation
    )

    # Remote Control is not enough: the arm must also be powered and brake-released.
    assert_robot_running(robot_ip)

    # A zero-force simulation exercises traversal and state handling without
    # loading a force program that would otherwise wait forever for movement.
    if contact_threshold == 0 and holding_force == 0:
        return True

    # IO writes robot inputs; Receive reads robot status.
    rtde_io = RTDEIOInterface(robot_ip, use_upper_range_registers=True)
    rtde_receive = RTDEReceiveInterface(
        robot_ip,
        variables=["timestamp", "output_int_register_42", "safety_status_bits"],
        use_upper_range_registers=True,
    )

    try:
        # Send physical values before starting the URP.
        parameters = {
            max_distance_register: max_distance,
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
        while rtde_receive.getOutputIntRegister(status_register) != 0:
            assert_robot_safe(rtde_receive)
            time.sleep(0.01)

        # Status 1 means real or simulated force success.
        force_reached = False

        # Wait for success (1), maximum distance (2), or timeout (3).
        while True:
            status = rtde_receive.getOutputIntRegister(status_register)
            assert_robot_safe(rtde_receive)

            if status == 1:
                # Wait, then tell the URP to end the hold and return.
                hold_deadline = time.monotonic() + hold_duration
                while True:
                    remaining = hold_deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    assert_robot_safe(rtde_receive)
                    time.sleep(min(0.05, remaining))
                if not rtde_io.setInputIntRegister(status_register, 1): raise RuntimeError("Could not send return acknowledgement.")
                force_reached = True
                break

            if status == 2:
                # No contact; the URP is already returning.
                break

            if status == 3:
                # Robot-side hold timeout; its cleanup still stops and returns.
                raise TimeoutError("Robot timed out while waiting for acknowledgement.")

            time.sleep(0.01)

        # Wait until the robot has returned to its initial pose.
        while rtde_receive.getOutputIntRegister(status_register) != 0:
            assert_robot_safe(rtde_receive)
            time.sleep(0.01)

        return force_reached
    finally:
        # Reset Python-owned inputs and close both connections.
        rtde_io.setInputIntRegister(status_register, 0)
        rtde_io.setInputIntRegister(simulation_register, 0)
        rtde_receive.disconnect()
        rtde_io.disconnect()


if __name__ == "__main__":
    input("Press Enter to load the URP and start, or Ctrl+C to cancel.")

    force_reached = apply_force("192.168.3.10", "Benoit/apply_force.urp",
                                0.050, 15.0, 20.0, simulation=False)
    print(f"force_reached = {force_reached}")
