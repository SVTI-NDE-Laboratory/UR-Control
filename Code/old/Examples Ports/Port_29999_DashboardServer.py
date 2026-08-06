import socket
from tkinter import Tk, messagebox

ROBOT_IP = "192.168.3.10"
DASHBOARD_PORT = 29999


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


def start_program(program_name):
    """Load the program and start it."""
 
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
    start_program("Benoit.urp")
