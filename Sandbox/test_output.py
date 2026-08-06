from rtde_receive import RTDEReceiveInterface
import time


rtde_r = RTDEReceiveInterface(
    "192.168.3.10",
    variables=["timestamp", "output_double_register_36"],
    use_upper_range_registers=True,
)

value = rtde_r.getOutputDoubleRegister(36)

print(value)