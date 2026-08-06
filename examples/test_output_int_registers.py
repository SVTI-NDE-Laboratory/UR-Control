"""Scan URScript output integer register mapping without moving the robot."""

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import assert_remote_control, get_rtde_receive, send_script


ROBOT_IP = "192.168.3.10"

# Try likely URScript addresses. Each address is tested separately so one bad
# address does not hide the others.
WRITE_ADDRESSES = [0, 1, 2, 3, 4, 18, 19, 20, 21, 22, 24, 25, 26, 27, 28, 42, 43]
LOWER_READ_ADDRESSES = [18, 19, 20, 21, 22]
UPPER_READ_ADDRESSES = [42, 43, 44, 45, 46]


def register_write_script(address: int, value: int) -> str:
    """Build a no-motion URScript that writes one output integer register.

    The `textmsg` lines help confirm on the pendant/log that the script ran.
    """

    script = f"""def python_register_test():
  textmsg("register_test_write_start", {address}, {value})
  write_output_integer_register({address}, {value})
  textmsg("register_test_write_done", {address}, {value})
end

python_register_test()
"""
    return script


def read_visible_registers(robot_ip: str) -> dict[int, int]:
    """Read all output integer registers exposed by this ur_rtde install.

    Lower and upper ranges require separate RTDE receive connections.
    """

    values = {}

    lower = get_rtde_receive(robot_ip, use_upper_range_registers=False)
    for address in LOWER_READ_ADDRESSES:
        values[address] = lower.getOutputIntRegister(address)
    lower.disconnect()

    upper = get_rtde_receive(robot_ip, use_upper_range_registers=True)
    for address in UPPER_READ_ADDRESSES:
        values[address] = upper.getOutputIntRegister(address)
    upper.disconnect()

    return values


def changed_registers(before: dict[int, int], after: dict[int, int]) -> dict[int, tuple[int, int]]:
    """Return registers whose read value changed after a URScript write.

    The result maps register address to `(before, after)`.
    """

    return {
        address: (before[address], after[address])
        for address in before
        if before[address] != after[address]
    }


if __name__ == "__main__":
    input("Press Enter to scan output int register mapping, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)

    for index, write_address in enumerate(WRITE_ADDRESSES, start=1):
        value = 1000 + index
        before = read_visible_registers(ROBOT_IP)
        send_script(ROBOT_IP, register_write_script(write_address, value))
        time.sleep(0.5)
        after = read_visible_registers(ROBOT_IP)
        changes = changed_registers(before, after)

        print(f"write_output_integer_register({write_address}, {value})")
        if changes:
            for read_address, (old_value, new_value) in changes.items():
                print(f"  RTDE read {read_address}: {old_value} -> {new_value}")
        else:
            print("  no visible RTDE output integer register changed")
