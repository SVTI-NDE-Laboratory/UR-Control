"""Publish complete JSON snapshots despite brief Windows destination locks."""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def write_json_atomic(path: str | Path, value: dict[str, Any]) -> None:
    """Replace a snapshot atomically, retrying permission errors for 0.5 s.

    Writers own separate staging files. On permanent failure, keep the previous
    snapshot, clean up the staging file, and propagate the error to the caller.
    """

    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary_path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, indent=2) + "\n")
        deadline = time.monotonic() + .5
        while True:
            try:
                temporary_path.replace(path)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.01)
    finally:
        temporary_path.unlink(missing_ok=True)
