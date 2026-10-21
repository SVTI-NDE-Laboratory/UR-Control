"""Build and check dist/RTM Cobot Studio.exe using the project virtual environment."""

from datetime import datetime, timezone
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist", help="Override the distribution folder, for example when checking a build while the normal exe is running.")
    distribution = parser.parse_args().dist_dir.resolve()
    if os.name != "nt":
        raise SystemExit("Build this Windows executable on Windows.")
    try:
        importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        raise SystemExit("Install build dependencies first: .\\.venv\\Scripts\\python.exe -m pip install -r tools/build_webapp2/requirements.txt")
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "temporary_data/pyinstaller-cache")
    start = time.perf_counter()
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--distpath", str(distribution),
                    "--workpath", str(ROOT / "temporary_data/webapp2-build"), str(ROOT / "tools/build_webapp2/webapp2.spec")],
                   cwd=ROOT, env=environment, check=True)
    built = time.perf_counter()
    executable = distribution / "RTM Cobot Studio.exe"
    subprocess.run([sys.executable, str(ROOT / "tools/build_webapp2/check_exe.py"), str(executable)],
                   cwd=ROOT, env=environment, check=True)
    end = time.perf_counter()
    with executable.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = {"built_at_utc": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "architecture": platform.machine(),
                "pyinstaller": importlib.metadata.version("pyinstaller"),
                "build_seconds": round(built - start, 1), "check_seconds": round(end - built, 1),
                "bytes": executable.stat().st_size, "sha256": checksum}
    (distribution / "UR15WebApp2-build.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "tools/build_webapp2/package.py"), "--dist-dir", str(distribution)], cwd=ROOT, env=environment, check=True)
    print(f"Ready: {executable}\nBuild: {metadata['build_seconds']} s; checks: {metadata['check_seconds']} s; size: {metadata['bytes'] / 1024**2:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
