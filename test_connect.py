import socket

ROBOT_IP = "192.168.0.10"  # change this
PORT = 29999

COMMANDS = [
    "robotmode",
    "safetymode",
    "programState",
    "running",
    "get loaded program",
]

def ask_robot(command: str) -> str:
    with socket.create_connection((ROBOT_IP, PORT), timeout=5) as sock:
        sock.recv(4096)  # welcome message
        sock.sendall((command + "\n").encode())
        return sock.recv(4096).decode(errors="ignore").strip()

def get_robot_status():
    status = {}
    for cmd in COMMANDS:
        try:
            status[cmd] = ask_robot(cmd)
        except Exception as e:
            status[cmd] = f"ERROR: {e}"
    return status

if __name__ == "__main__":
    status = get_robot_status()

    print("\nUR Robot Status")
    print("----------------")
    for key, value in status.items():
        print(f"{key}: {value}")