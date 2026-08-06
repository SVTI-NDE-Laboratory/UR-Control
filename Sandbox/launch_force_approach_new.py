"""Launch force_approach_new.script with a TCP result/release server.

This sandbox does not use the main measurement flow. It starts the Python TCP
server first, sends the URScript to the robot, then prints every message received
from the robot.
"""

import socket
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROBOT_DIR = PROJECT_ROOT / "Code" / "Robot"
if str(ROBOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROBOT_DIR))

from robot_connection import assert_remote_control, send_script


ROBOT_IP = "192.168.3.10"
SCRIPT_FILE = PROJECT_ROOT / "Configuration" / "Measurement Programs" / "force_approach_new.script"

# The URScript currently connects to python_ip="192.168.3.100", python_port=50001.
# Binding to 0.0.0.0 lets Python accept that connection on any local interface.
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 50001
SERVER_TIMEOUT = 60.0

# Sandbox behavior: after CONTACT, simulate acquisition briefly, then release.
AUTO_RELEASE = True
SIMULATED_ACQUISITION_TIME = 1.0


def read_script(path: str | Path) -> str:
    """Read the URScript text to send through the robot script port.

    The script is sent exactly as stored in Configuration/Measurement Programs.
    """

    return Path(path).read_text(encoding="utf-8")


def receive_line(connection: socket.socket) -> str:
    """Receive one newline-terminated robot message.

    The robot sends messages with socket_send_line(), so each message ends with a newline.
    """

    chunks = []
    while True:
        chunk = connection.recv(1)
        if not chunk:
            break
        if chunk == b"\n":
            break
        chunks.append(chunk)

    return b"".join(chunks).decode("utf-8", errors="replace").strip()


def send_release(connection: socket.socket) -> None:
    """Tell the robot it can leave the force hold phase.

    force_approach_new.script waits for the exact line RELEASE.
    """

    connection.sendall(b"RELEASE\n")


def handle_robot_messages(server: socket.socket) -> bool:
    """Read force approach messages and return whether contact was reached.

    CONNECTED means the robot opened the socket before starting force motion.
    CONTACT means the robot is holding in force mode and waiting for RELEASE.
    NO_CONTACT means max travel was reached before force.
    RELEASED confirms the robot received RELEASE and will return to its saved pose.
    """

    try:
        connection, address = server.accept()
    except socket.timeout as error:
        raise TimeoutError(
            "No robot connection received. Check that force_approach_new.script uses "
            "python_ip='192.168.3.100', python_port=50001, that this listener is "
            "running before the URP starts, and that Windows Firewall allows inbound "
            "TCP on port 50001."
        ) from error
    print(f"Robot socket connected from {address}")

    contact_reached = False
    with connection:
        connection.settimeout(SERVER_TIMEOUT)

        while True:
            message = receive_line(connection)
            if not message:
                print("Robot socket closed")
                return contact_reached

            print(f"Robot message: {message}")

            if message == "CONNECTED":
                print("Robot confirmed socket connection before force approach")

            elif message == "CONTACT":
                contact_reached = True
                if AUTO_RELEASE:
                    print(f"Simulated acquisition for {SIMULATED_ACQUISITION_TIME:.1f} s")
                    time.sleep(SIMULATED_ACQUISITION_TIME)
                    print("Sending RELEASE")
                    send_release(connection)
                else:
                    input("Press Enter to send RELEASE to the robot.")
                    send_release(connection)

            elif message == "NO_CONTACT":
                return False

            elif message == "RELEASED":
                return True

            elif message == "TIMEOUT":
                return contact_reached


def launch_script_and_wait() -> bool:
    """Start the TCP server, launch the robot script, and wait for the result.

    The server is listening before the robot script is sent, so the robot can
    connect immediately before starting motion.
    """

    script = read_script(SCRIPT_FILE)

    with socket.create_server((SERVER_HOST, SERVER_PORT), reuse_port=False) as server:
        server.settimeout(SERVER_TIMEOUT)
        print(f"Listening for robot messages on {SERVER_HOST}:{SERVER_PORT}")

        send_script(ROBOT_IP, script)
        print(f"Sent script: {SCRIPT_FILE}")

        return handle_robot_messages(server)


if __name__ == "__main__":
    input("Press Enter to launch force_approach_new.script, or Ctrl+C to cancel.")
    assert_remote_control(ROBOT_IP)

    success = launch_script_and_wait()
    print(f"force_approach_success={success}")
