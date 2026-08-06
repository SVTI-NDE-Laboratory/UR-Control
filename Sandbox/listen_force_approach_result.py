"""Listen for force approach messages while the URP is started manually."""

import socket

from launch_force_approach_new import (
    SERVER_HOST,
    SERVER_PORT,
    SERVER_TIMEOUT,
    handle_robot_messages,
)


EXPECTED_PYTHON_IP = "192.168.3.100"


def local_ipv4_addresses() -> list[str]:
    """Return local IPv4 addresses visible from Python.

    This helps verify which address the robot should use in socket_open().
    """

    addresses = []
    host_name = socket.gethostname()
    for result in socket.getaddrinfo(host_name, None, socket.AF_INET):
        address = result[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


if __name__ == "__main__":
    print("Start this first, then press Play on the robot tablet.")
    print("The URP Script node must contain:")
    print(f'  python_ip = "{EXPECTED_PYTHON_IP}"')
    print(f"  python_port = {SERVER_PORT}")
    print(f"Local IPv4 addresses seen by Python: {local_ipv4_addresses()}")

    with socket.create_server((SERVER_HOST, SERVER_PORT), reuse_port=False) as server:
        server.settimeout(SERVER_TIMEOUT)
        print(f"Listening for robot messages on {SERVER_HOST}:{SERVER_PORT}")
        success = handle_robot_messages(server)

    print(f"force_approach_success={success}")
