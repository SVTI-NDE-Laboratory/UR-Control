"""Run the original automatic sequence with observation hooks, without editing it."""

import sys
import os
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path
import traceback

from .settings import ROOT, ROUTINE_FILE, ROBOT_IP, PROFILE
from .feedback import Feedback, TrackedServer
from .flexible_worker import classify_plane
from read_routines import read_routines_file


class ConsoleLog:
    """Keep the terminal visible while flushing each Python write to the run log."""
    def __init__(self, console, log):
        self.console, self.log = console, log

    def write(self, text):
        self.log.write(text)
        self.log.flush()
        if self.console is not None:
            self.console.write(text)
            self.console.flush()
        return len(text)

    def flush(self):
        self.log.flush()
        if self.console is not None:
            self.console.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


@contextmanager
def console_logging(path):
    """Retain stdout, stderr and an uncaught traceback when Show terminal is enabled."""
    with Path(path).open("a", encoding="utf-8") as log:
        with redirect_stdout(ConsoleLog(sys.stdout, log)), redirect_stderr(ConsoleLog(sys.stderr, log)):
            try:
                yield
            except BaseException:
                # The interpreter prints to the restored console after propagation.
                traceback.print_exc(file=log)
                raise


def main():
    """Attach feedback to the sequence's existing receiver and acquisition server."""
    sys.path.insert(0, str(ROOT / "src/program/commands"))
    import run_measurement_sequence as sequence
    import run_measurements as measurements
    from data_acquisition import server_control
    output = Path(sys.argv[sys.argv.index("--output-dir") + 1])
    feedback = Feedback(output / "feedback.json", read_routines_file(ROUTINE_FILE), classifier=classify_plane)
    original_connect = sequence.get_rtde_receive
    original_server = sequence.AcquisitionControlServer
    original_force = measurements.apply_force
    original_ip = sequence.ROBOT_IP
    original_read_config = sequence.read_server_config
    sequence.ROBOT_IP = ROBOT_IP
    sequence.read_server_config = lambda: server_control.read_server_config(PROFILE.paths["acquisition_config"])

    class ObservedReceiver:
        def __init__(self, receiver):
            self.receiver = receiver

        def __getattr__(self, name):
            return getattr(self.receiver, name)

        def disconnect(self):
            feedback.detach()
            return self.receiver.disconnect()

    def connect(*args, **kwargs):
        receiver = ObservedReceiver(original_connect(*args, **kwargs))
        feedback.attach(receiver)
        return receiver

    class ObservedServer(TrackedServer):
        def start(self):
            super().start()
            feedback.server = self

        def stop(self):
            super().stop()
            feedback.server = None

    sequence.get_rtde_receive = connect
    sequence.AcquisitionControlServer = ObservedServer
    def observed_force(*args, **kwargs):
        with feedback.force_cycle():
            return original_force(*args, **kwargs)

    measurements.apply_force = observed_force
    feedback.start()
    try:
        sequence.main()
    finally:
        sequence.get_rtde_receive = original_connect
        sequence.AcquisitionControlServer = original_server
        sequence.ROBOT_IP = original_ip
        sequence.read_server_config = original_read_config
        measurements.apply_force = original_force
        feedback.close()


if __name__ == "__main__":
    log_path = os.environ.get("UR15_WORKER_CONSOLE_LOG")
    if log_path:
        with console_logging(log_path):
            main()
    else:
        main()
