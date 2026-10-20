"""Write the current measurement state."""

from pathlib import Path

from atomic_json import write_json_atomic


def write_state(path: str | Path, state: dict) -> None:
    """Write the current program state as JSON.

    The state file is meant for monitoring/debugging the running sequence.
    """

    write_json_atomic(path, state)
