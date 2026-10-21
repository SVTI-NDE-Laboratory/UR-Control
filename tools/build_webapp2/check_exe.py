"""Check a built exe from an unrelated working folder, without robot motion."""

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
from urllib.request import Request, urlopen


def check(executable):
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix="webapp2-exe-check-") as temporary:
        directory = Path(temporary).resolve()
        data = directory / "local data"
        environment = {key: value for key, value in os.environ.items() if not key.startswith("UR15_")}
        environment["UR15_WEBAPP_DATA_DIR"] = str(data)
        environment["UR15_WEBAPP_LOCATION_FILE"] = str(directory / "location.json")
        for arguments in (["--check-bundle", "--data-dir", str(data)], *[
            ["--worker", f"src.program.webapp2.{name}_worker", "--check-import"]
            for name in ("manual", "flexible", "measurement")
        ]):
            result = subprocess.run([str(executable), *arguments], cwd=directory, env=environment,
                                    capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError(f"Executable check failed: {arguments}\n{result.stdout}\n{result.stderr}")
            print(result.stdout.strip(), flush=True)
        process = subprocess.Popen([str(executable), "--data-dir", str(data), "--no-browser"],
                                   cwd=directory, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        lines = queue.Queue()
        output = []

        def collect():
            for line in process.stdout:
                output.append(line)
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        try:
            while True:
                line = lines.get(timeout=60)
                if line is None:
                    raise RuntimeError("Executable exited before starting the web interface.\n" + "".join(output))
                if line.startswith("RTM Cobot Studio: "):
                    base = line.split(": ", 1)[1].strip().removesuffix("/manual")
                    break
            for route in ("/manual", "/settings", "/configuration", "/v2-static/app.js", "/v2-static/styles.css", "/v2-static/dialogs.js", "/v2-static/dialogs.css", "/v2-static/automatic.js", "/v2-static/automatic.css", "/v2-static/svti-logo.svg", "/v2-static/svti-logo.ico", "/static/styles.css", "/api/manual/options", "/api/settings/routines"):
                with urlopen(base + route, timeout=20) as response:
                    if response.status != 200 or not response.read():
                        raise RuntimeError(f"Bundled route failed: {route}")
            with urlopen(base + "/api/settings", timeout=20) as response:
                settings = json.load(response)
            if Path(settings["data_directory"]) != data:
                raise RuntimeError("Executable did not use the isolated data folder.")
            with urlopen(Request(base + "/api/close", data=b"{}", headers={"Content-Type": "application/json"}), timeout=20) as response:
                if not json.load(response)["closed"]:
                    raise RuntimeError("Executable did not acknowledge shutdown.")
            if process.wait(timeout=30):
                raise RuntimeError("Executable failed during shutdown.\n" + "".join(output))
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=15)
            reader.join(timeout=3)
            process.stdout.close()
    print("Executable checks passed: UI, assets, defaults, RTDE imports, worker entry points and shutdown. No robot connection opened.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    check(parser.parse_args().executable)
