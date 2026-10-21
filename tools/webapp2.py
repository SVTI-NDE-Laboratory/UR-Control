"""Launch WebApp 2.0 locally: python tools/webapp2.py."""

import socket
import argparse
import os
import runpy
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    # A frozen executable also serves as its own worker entry point.
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        module = sys.argv[2]
        if module not in {"src.program.webapp2.manual_worker", "src.program.webapp2.flexible_worker",
                          "src.program.webapp2.measurement_worker"}:
            raise ValueError("Unknown WebApp2 worker.")
        sys.argv = [module, *sys.argv[3:]]
        runpy.run_module(module, run_name="__main__")
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="Override AppData for local testing.")
    parser.add_argument("--check-config", action="store_true", help="Initialize and validate files, then exit without starting the server.")
    parser.add_argument("--no-browser", action="store_true", help="Start the server without opening a browser.")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["UR15_WEBAPP_DATA_DIR"] = str(args.data_dir.resolve())
        os.environ["UR15_WEBAPP_LOCATION_FILE"] = str(args.data_dir.resolve() / "location.json")
    from src.program.webapp2.profile import prepare_startup
    prepare_startup(interactive=not args.check_config)
    # Read preferences and validate the full profile before importing the app.
    from src.program.webapp2.settings import PROFILE
    print(f"Local data: {PROFILE.data_dir}")
    if args.check_config:
        print("Configuration OK. No robot connection was opened.")
        return
    from src.program.webapp2.server import api
    import uvicorn
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(2048)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(api, log_level="warning"))
        api.state.uvicorn_server = server
        url = f"http://127.0.0.1:{port}/manual"
        print(f"UR15 WebApp 2.0: {url}")
        print("Press Ctrl+C here to close the control panel.")
        if not args.no_browser:
            threading.Timer(0.4, webbrowser.open, args=(url,)).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError) as error:
        print(f"WebApp2 startup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
