import socket
from tkinter import Tk, messagebox


ROBOT_IP = "192.168.3.10"
DASHBOARD_PORT = 29999
PROGRAM_NAME = "Benoit/Code Base/Main_Horizontal_1Line_Register.urp"

# Change these five values for each run.
avoid_start = 5  
avoid_end = 7
avoid_gap = 0.05
line_incr = 0.1
line_length = 1

# Register mapping used by the UR program.
# In Polyscope/URScript, read them with read_input_float_register(register_number).
RTDE_FLOAT_VALUES = {
    18: avoid_start,
    19: avoid_end,
    20: avoid_gap,
    21: line_incr,
    22: line_length,
}


def dashboard_command(command: str) -> str:
    """Connect to the Dashboard server, send one command and return its response."""

    with socket.create_connection((ROBOT_IP, DASHBOARD_PORT), timeout=5) as sock:
        sock.recv(1024)
        sock.sendall((command + "\n").encode())
        return sock.recv(1024).decode().strip()


def robot_status() -> None:
    """Print basic robot information."""

    print("Robot mode    :", dashboard_command("robotmode"))
    print("Program state :", dashboard_command("programState"))
    print("Loaded program:", dashboard_command("get loaded program"))


def set_rtde_float_registers(values_by_register: dict[int, float]) -> None:
    """Write all configured float values through RTDE input double registers."""

    try:
        from rtde_io import RTDEIOInterface
    except ImportError as error:
        raise RuntimeError(
            "The ur_rtde Python package is required. Install it with "
            "'python -m pip install ur_rtde'."
        ) from error

    rtde_io = RTDEIOInterface(ROBOT_IP)
    try:
        for register, value in values_by_register.items():
            rtde_io.setInputDoubleRegister(register, float(value))
            print(f"Set RTDE input double register {register} = {value}")
    finally:
        rtde_io.disconnect()


def confirm_program_start() -> bool:
    """Ask the user for a final confirmation before the robot starts moving."""

    root = Tk()
    root.withdraw()
    try:
        return messagebox.askokcancel(
            "Robot program start",
            "Move away from the robot.\n\n"
            "Be ready to click Stop immediately if needed.\n\n"
            "Click OK to start the program.",
        )
    finally:
        root.destroy()


def start_program(program_name: str) -> None:
    """Load the selected program and start it after confirmation."""

    print(dashboard_command(f"load {program_name}"))

    if not confirm_program_start():
        print("Program start canceled by user.")
        return

    print(dashboard_command("play"))


def main() -> None:
    robot_status()
    set_rtde_float_registers(RTDE_FLOAT_VALUES)
    start_program(PROGRAM_NAME)


if __name__ == "__main__":
    main()
