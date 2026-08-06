from rtde_io import RTDEIOInterface
from rtde_receive import RTDEReceiveInterface
import time

ROBOT_IP = "192.168.3.10"
REGISTER = 42

rtde_io = RTDEIOInterface(
    ROBOT_IP,
    use_upper_range_registers=True,
)

rtde_r = RTDEReceiveInterface(
    ROBOT_IP,
    variables=[
        "timestamp",
        "output_int_register_42",
    ],
    use_upper_range_registers=True,
)

# Reset Python → robot acknowledgment
rtde_io.setInputIntRegister(REGISTER, 0)

print("Waiting for the robot program to start...")

# Reject a stale status left by a previous execution.
# The URScript writes output register 42 to 0 at startup.
while rtde_r.getOutputIntRegister(REGISTER) != 0:
    time.sleep(0.01)

print("Robot program initialized. Waiting for force approach...")

while True:
    status = rtde_r.getOutputIntRegister(REGISTER)

    if status == 1:
        print("Contact detected. Robot is maintaining force.")
        time.sleep(3.0)

        success = rtde_io.setInputIntRegister(REGISTER, 1)
        print("Return acknowledgement sent:", success)
        break

    if status == 2:
        print("Maximum distance reached without contact.")
        break

    if status == 3:
        print("Robot timed out while waiting for acknowledgment.")
        break

    time.sleep(0.01)

# Wait for the robot to return and reset its output.
while rtde_r.getOutputIntRegister(REGISTER) != 0:
    time.sleep(0.01)

# Reset Python's acknowledgment for the next run.
rtde_io.setInputIntRegister(REGISTER, 0)

print("Cycle completed.")