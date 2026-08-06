from rtde_io import RTDEIOInterface
from rtde_receive import RTDEReceiveInterface
import time

ROBOT_IP = "192.168.3.10"
REGISTER = 42

rtde_io = RTDEIOInterface(
    ROBOT_IP,
    use_upper_range_registers=True
)

rtde_r = RTDEReceiveInterface(
    ROBOT_IP,
    variables=[
        "timestamp",
        "output_int_register_42",
    ],
    use_upper_range_registers=True
)

# Reset Python → robot acknowledgement
rtde_io.setInputIntRegister(REGISTER, 0)

print("Waiting for robot to reach the target...")

while rtde_r.getOutputIntRegister(REGISTER) != 1:
    time.sleep(0.01)

print("Target reached. Waiting 3 seconds...")
time.sleep(3.0)

# Tell the robot to return
success = rtde_io.setInputIntRegister(REGISTER, 1)
print("Acknowledgement sent:", success)

# Wait until the robot clears its signal
while rtde_r.getOutputIntRegister(REGISTER) != 0:
    time.sleep(0.01)

# Reset acknowledgement for the next cycle
rtde_io.setInputIntRegister(REGISTER, 0)

print("Cycle completed.")