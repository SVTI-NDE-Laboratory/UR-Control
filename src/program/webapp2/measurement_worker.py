"""Run the original automatic sequence with observation hooks, without editing it."""

import sys
from pathlib import Path

from .settings import ROOT, ROUTINE_FILE
from .feedback import Feedback, TrackedServer
from .flexible_worker import classify_plane
from read_routines import read_routines_file


def main():
    """Attach feedback to the sequence's existing receiver and acquisition server."""
    sys.path.insert(0, str(ROOT / "src/program/commands"))
    import run_measurement_sequence as sequence
    import run_measurements as measurements
    output = Path(sys.argv[sys.argv.index("--output-dir") + 1])
    feedback = Feedback(output / "feedback.json", read_routines_file(ROUTINE_FILE), classifier=classify_plane)
    original_connect = sequence.get_rtde_receive
    original_server = sequence.AcquisitionControlServer
    original_force = measurements.apply_force

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
        measurements.apply_force = original_force
        feedback.close()


if __name__ == "__main__":
    main()
