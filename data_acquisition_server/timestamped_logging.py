"""Line-oriented terminal mirroring with local timestamps."""

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import TextIO


class TimestampedTeeStream:
    """Write timestamped lines to one terminal stream and a shared log file."""

    def __init__(
        self,
        terminal_stream: TextIO,
        log_stream: TextIO,
        lock: threading.Lock,
    ) -> None:
        self.terminal_stream = terminal_stream
        self.log_stream = log_stream
        self.lock = lock
        self.at_line_start = True

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self.lock:
            for part in text.splitlines(keepends=True):
                prefix = ""
                if self.at_line_start:
                    timestamp = datetime.now().astimezone().isoformat(
                        timespec="milliseconds"
                    )
                    prefix = f"[{timestamp}] "
                rendered = prefix + part
                self.terminal_stream.write(rendered)
                self.log_stream.write(rendered)
                self.at_line_start = part.endswith(("\n", "\r"))
            self.terminal_stream.flush()
            self.log_stream.flush()
        return len(text)

    def flush(self) -> None:
        with self.lock:
            self.terminal_stream.flush()
            self.log_stream.flush()

    def isatty(self) -> bool:
        return self.terminal_stream.isatty()

    @property
    def encoding(self) -> str | None:
        return self.terminal_stream.encoding


def install_timestamped_tee(log_path: str | Path) -> TextIO:
    """Timestamp and mirror subsequent stdout/stderr to ``log_path``."""

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = path.open("w", encoding="utf-8", buffering=1)
    lock = threading.Lock()
    sys.stdout = TimestampedTeeStream(sys.stdout, log_stream, lock)
    sys.stderr = TimestampedTeeStream(sys.stderr, log_stream, lock)
    return log_stream
