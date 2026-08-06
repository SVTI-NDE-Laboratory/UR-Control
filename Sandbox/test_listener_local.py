"""Local self-test for the sandbox TCP listener port."""

import socket
import threading

from launch_force_approach_new import SERVER_PORT, receive_line, send_release


HOST = "127.0.0.1"
MESSAGE = "CONTACT"


def client_send_message() -> None:
    """Connect locally and send one robot-like line.

    This confirms Python can bind and accept connections on the configured port.
    """

    with socket.create_connection((HOST, SERVER_PORT), timeout=5) as connection:
        connection.sendall((MESSAGE + "\n").encode("utf-8"))
        reply = receive_line(connection)
        print(f"Client received: {reply}")


if __name__ == "__main__":
    with socket.create_server((HOST, SERVER_PORT), reuse_port=False) as server:
        thread = threading.Thread(target=client_send_message)
        thread.start()

        connection, address = server.accept()
        print(f"Server accepted connection from {address}")

        with connection:
            message = receive_line(connection)
            print(f"Server received: {message}")
            send_release(connection)

        thread.join()
