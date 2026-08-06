"""Sandbox test for robot-written RTDE output registers.

Python cannot set RTDE output registers directly. This script sends small
no-motion URScript snippets that call write_output_*_register(), then Python
reads the visible RTDE output register ranges.
"""

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import assert_remote_control, get_rtde_receive, send_script


ROBOT_IP = "192.168.3.10"
WRITE_ADDRESSES = list(range(0, 8)) + list(range(12, 20)) + list(range(24, 29)) + list(range(42, 47))
LOWER_READ_ADDRESSES = list(range(0, 48))
UPPER_READ_ADDRESSES = list(range(0, 48))


def output_integer_register_write_script(address: int, value: int) -> str:
    """Build a no-motion URScript that writes one integer output register.

    If the write address is invalid, the tablet/log should show the script error.
    """

    script = f"""def python_output_register_test():
  textmsg("output_integer_register_test_start", {address})
  write_output_integer_register({address}, {value})
  textmsg("output_integer_register_test_done", {address})
end

python_output_register_test()
"""
    return script


def output_float_register_write_script(address: int, value: float) -> str:
    """Build a no-motion URScript that writes one float output register.

    Python reads these with getOutputDoubleRegister().
    """

    script = f"""def python_output_register_test():
  textmsg("output_float_register_test_start", {address})
  write_output_float_register({address}, {value})
  textmsg("output_float_register_test_done", {address})
end

python_output_register_test()
"""
    return script


def read_output_registers(robot_ip: str, use_upper_range_registers: bool) -> dict[str, dict[int, int | float]]:
    """Read supported output integer and double registers from one RTDE range.

    Unsupported addresses are skipped because supported ranges vary by recipe.
    """

    addresses = UPPER_READ_ADDRESSES if use_upper_range_registers else LOWER_READ_ADDRESSES
    rtde_receive = get_rtde_receive(robot_ip, use_upper_range_registers=use_upper_range_registers)

    try:
        int_values = {}
        double_values = {}

        for address in addresses:
            try:
                int_values[address] = rtde_receive.getOutputIntRegister(address)
            except ValueError:
                pass

            try:
                double_values[address] = rtde_receive.getOutputDoubleRegister(address)
            except ValueError:
                pass

        return {"int": int_values, "double": double_values}
    finally:
        rtde_receive.disconnect()


def read_all_visible_output_registers(robot_ip: str) -> dict[str, dict[int, int | float]]:
    """Read both lower and upper RTDE output register ranges.

    This is the complete range exposed by the installed ur_rtde convenience API.
    """

    lower = read_output_registers(robot_ip, use_upper_range_registers=False)
    upper = read_output_registers(robot_ip, use_upper_range_registers=True)

    return {
        "int": {f"lower:{address}": value for address, value in lower["int"].items()}
        | {f"upper:{address}": value for address, value in upper["int"].items()},
        "double": {f"lower:{address}": value for address, value in lower["double"].items()}
        | {f"upper:{address}": value for address, value in upper["double"].items()},
    }


def print_changes(before: dict, after: dict) -> None:
    """Print only register values that changed after the URScript write.

    If nothing changes, Python did not observe the robot-side output write.
    """

    changed = False
    for kind in ["int", "double"]:
        for address, old_value in before[kind].items():
            new_value = after[kind][address]
            if old_value != new_value:
                changed = True
                print(f"  {kind} register {address}: {old_value} -> {new_value}")

    if not changed:
        print("  no visible RTDE output register changed")


if __name__ == "__main__":
    input("Press Enter to scan robot-written output registers, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)

    print("\nInteger output register scan")
    for index, address in enumerate(WRITE_ADDRESSES, start=1):
        int_value = 2000 + index

        before = read_all_visible_output_registers(ROBOT_IP)
        send_script(ROBOT_IP, output_integer_register_write_script(address, int_value))
        time.sleep(0.5)
        after = read_all_visible_output_registers(ROBOT_IP)

        print(f"write_output_integer_register({address}, {int_value})")
        print_changes(before, after)

    print("\nFloat output register scan")
    for index, address in enumerate(WRITE_ADDRESSES, start=1):
        double_value = 20.0 + index / 10.0

        before = read_all_visible_output_registers(ROBOT_IP)
        send_script(ROBOT_IP, output_float_register_write_script(address, double_value))
        time.sleep(0.5)
        after = read_all_visible_output_registers(ROBOT_IP)

        print(f"write_output_float_register({address}, {double_value})")
        print_changes(before, after)
