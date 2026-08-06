from rtde_io import RTDEIOInterface

rtde_io = RTDEIOInterface("192.168.3.10")
rtde_io.setInputDoubleRegister(42, 2404.0)


rtde_r = RTDEReceiveInterface(
    "192.168.3.10",
    variables=["output_double_register_36"],
    use_upper_range_registers=True,
)

confirmed_value = rtde_r.getOutputDoubleRegister(42)
print(confirmed_value)