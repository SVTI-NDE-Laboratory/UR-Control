r"""Minimal TCP server that answers ALIVE with OK.

Run:
    python examples\example_acquisition_control_server.py
"""

import argparse
import socketserver


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Handle short client connections concurrently."""

    allow_reuse_address = True
    daemon_threads = True


class RequestHandler(socketserver.BaseRequestHandler):
    """Read one request and answer OK only for ALIVE."""

    def handle(self) -> None:
        raw_request = self.request.recv(1024)
        decoded_request = raw_request.decode("utf-8", errors="replace")
        request = decoded_request.strip()
        client = f"{self.client_address[0]}:{self.client_address[1]}"
        print(f"Raw bytes from client {client}: {raw_request!r}")
        print(f"Decoded text from client {client}: {decoded_request!r}")
        print(f"Hex bytes from client {client}: {raw_request.hex(' ')}")
        if request.upper() == "ALIVE":
            response = "OK"
            print(f"Received ALIVE from client {client}. Answered OK to client.")
        else:
            response = "ERR"
            print(f"Received unsupported request {request!r} from client {client}. Answered ERR.")
        self.request.sendall((response + "\n").encode("utf-8"))


def parse_args() -> argparse.Namespace:
    """Return command-line options."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5055)
    return parser.parse_args()


def main() -> None:
    """Run the ALIVE-only test server."""

    args = parse_args()
    server = ThreadedTCPServer((args.host, args.port), RequestHandler)
    print(f"Listening on {args.host}:{args.port}")
    print("Waiting for ALIVE. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
