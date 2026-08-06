"""Write the current measurement state."""

import json
from pathlib import Path


def write_state(path: str | Path, state: dict) -> None:
    """Write the current program state as JSON.

    The state file is meant for monitoring/debugging the running sequence.
    """

    Path(path).write_text(json.dumps(state, indent=2), encoding="utf-8")
