"""Write the current measurement state."""

import json
from pathlib import Path


def write_state(path: str | Path, state: dict) -> None:
    """Write the current program state as JSON.

    The state file is meant for monitoring/debugging the running sequence.
    """

    state_path = Path(path)
    temporary_path = state_path.with_suffix(state_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary_path.replace(state_path)
