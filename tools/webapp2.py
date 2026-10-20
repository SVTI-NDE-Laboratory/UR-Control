"""Launch WebApp 2.0 locally: python tools/webapp2.py."""

import socket
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.program.webapp2.server import api
import uvicorn


if __name__ == "__main__":
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2048)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api, log_level="warning"))
        api.state.uvicorn_server = server
        url = f"http://127.0.0.1:{port}/manual"
        print(f"UR15 WebApp 2.0: {url}")
        print("Press Ctrl+C here to close the control panel.")
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
        server.run(sockets=[listener])
