"""Start the local FastAPI control panel and open it in a browser."""

import socket
import threading
import webbrowser

import uvicorn

if __package__:
    from .server import api
else:
    from server import api


def main() -> None:
    """Run Uvicorn on a free local port until the operator closes the app."""

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    port = listener.getsockname()[1]

    config = uvicorn.Config(api, log_level="warning")
    server = uvicorn.Server(config)
    api.state.uvicorn_server = server
    url = f"http://127.0.0.1:{port}/configuration"
    print(f"UR15 control panel: {url}")
    print("Press Ctrl+C here to close the control panel.")
    threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()
