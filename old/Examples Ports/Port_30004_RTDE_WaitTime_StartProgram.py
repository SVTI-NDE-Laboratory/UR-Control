import socket
from tkinter import Tk, messagebox

ROBOT_IP = "192.168.3.10"
DASHBOARD_PORT = 29999

PROGRAM_NAME = "Benoit.urp"
WAIT_TIME_SECONDS = 10.0
RTDE_WAIT_TIME_REGISTER = 18


def dashboard_command(command: str) -> str:
    """Connect to the Dashboard server, send one command and return its response."""

    with socket.create_connection((ROBOT_IP, DASHBOARD_PORT), timeout=5) as sock:

        # Consume the welcome message
        sock.recv(1024)

        # Send the command
        sock.sendall((command + "\n").encode())

        # Return the response
        return sock.recv(1024).decode().strip()


def robot_status():
    """Print basic robot information."""

    print("Robot mode    :", dashboard_command("robotmode"))
    print("Program state :", dashboard_command("programState"))
    print("Loaded program:", dashboard_command("get loaded program"))


def set_wait_time_rtde(wait_time_seconds: float) -> None:
    """Write WaitTime through an RTDE input double register."""

    try:
        from rtde_io import RTDEIOInterface
    except ImportError as error:
        raise RuntimeError(
            "The ur_rtde Python package is required. Install it with "
            "'python -m pip install ur_rtde'."
        ) from error

    rtde_io = RTDEIOInterface(ROBOT_IP)
    try:
        rtde_io.setInputDoubleRegister(RTDE_WAIT_TIME_REGISTER, wait_time_seconds)
    finally:
        rtde_io.disconnect()

    print(f"WaitTime RTDE register {RTDE_WAIT_TIME_REGISTER} set to {wait_time_seconds} seconds.")


def start_program(program_name: str) -> None:
    """Set WaitTime, load the program, ask for confirmation, and start it."""

    set_wait_time_rtde(WAIT_TIME_SECONDS)
    print(dashboard_command(f"load {program_name}"))

    root = Tk()
    root.withdraw()
    try:
        ready_to_start = messagebox.askokcancel(
            "Robot program start",
            "Move away from the robot.\n\n"
            "Be ready to click Stop immediately if needed.\n\n"
            "Click OK to start the program.",
        )
    finally:
        root.destroy()

    if not ready_to_start:
        print("Program start canceled by user.")
        return

    print(dashboard_command("play"))


if __name__ == "__main__":

    robot_status()

    start_program(PROGRAM_NAME)
