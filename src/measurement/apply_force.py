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

from robot_connection import assert_remote_control, load_and_play_urp


def apply_force(robot_ip: str, program_path: str, max_distance: float, contact_threshold: float, holding_force: float, simulation: bool = False) -> bool:
    """Run a force cycle and block until the robot returns; simulation can report maximum distance as success."""

    # Registers: status/ack, max distance, contact threshold, holding force, simulation.
    status_register, max_distance_register, contact_threshold_register, holding_force_register, simulation_register = 42, 43, 44, 45, 46

    # Python ends the hold after this fixed measurement period.
    hold_duration = 3.0

    # Validate values before connecting.
    if max_distance <= 0: raise ValueError("max_distance must be positive.")
    if contact_threshold <= 0: raise ValueError("contact_threshold must be positive.")
    if holding_force < contact_threshold: raise ValueError("holding_force must be at least contact_threshold.")

    # Confirm the robot accepts remote program commands.
    assert_remote_control(robot_ip)

    # IO writes robot inputs; Receive reads robot status.
    rtde_io = RTDEIOInterface(robot_ip, use_upper_range_registers=True)
    rtde_receive = RTDEReceiveInterface(robot_ip, variables=["timestamp", "output_int_register_42"], use_upper_range_registers=True)

    try:
        # Send physical values before starting the URP.
        parameters = {max_distance_register: max_distance, contact_threshold_register: contact_threshold, holding_force_register: holding_force}

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
            time.sleep(0.01)

        # Status 1 means real or simulated force success.
        force_reached = False

        # Wait for success (1), maximum distance (2), or timeout (3).
        while True:
            status = rtde_receive.getOutputIntRegister(status_register)

            if status == 1:
                # Wait, then tell the URP to end the hold and return.
                time.sleep(hold_duration)
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
