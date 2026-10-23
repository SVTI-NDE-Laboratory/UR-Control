"""Finished measurement workers remove runtime files and retain final UI state."""

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.program.webapp2 import server
from src.program.webapp2.control import ControlWorkers


class ResultsCleanupTests(unittest.TestCase):
    def test_cleanup_waits_for_exit_and_retains_final_status_for_both_endpoints(self):
        for mode, code in (("idle", 0), ("error", 1), ("stopped", -1)):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                owner = ControlWorkers()
                owner.directory = directory
                owner._state_file = directory / "state.json"
                owner._kind = "measurement"
                process = Mock()
                owner._process = process
                exited = threading.Event()
                waiting = threading.Event()

                def wait_for_exit():
                    waiting.set()
                    if not exited.wait(5):
                        raise TimeoutError("Test worker did not exit")
                    return code

                process.wait.side_effect = wait_for_exit
                process.poll.side_effect = lambda: code if exited.is_set() else None
                process.returncode = code
                program = {"mode": mode, "message": "Final run status", "measurement_index": 4}
                owner._state_file.write_text(json.dumps(program))
                (directory / "feedback.json").write_text(json.dumps({"robot_connected": True}))
                retained = ("measurement_configuration.json", "measurement_results.json", "session.json", "worker.log", "program.log")
                for name in retained:
                    (directory / name).write_text("keep")

                monitor = threading.Thread(target=owner._finish_measurement, args=(process, owner._state_file, directory))
                monitor.start()
                try:
                    self.assertTrue(waiting.wait(2))
                    self.assertTrue(owner._state_file.exists())
                    self.assertTrue((directory / "feedback.json").exists())
                finally:
                    exited.set()
                    monitor.join(5)
                self.assertFalse(monitor.is_alive())
                self.assertFalse(owner._state_file.exists())
                self.assertFalse((directory / "feedback.json").exists())
                self.assertTrue(all((directory / name).read_text() == "keep" for name in retained))
                worker, final, feedback = owner.details()
                self.assertFalse(worker["running"])
                self.assertEqual(final, program)
                self.assertFalse(feedback["robot_connected"])
                with patch.object(server, "workers", owner), patch.object(server.legacy, "measurement_status", return_value={"program_state": {"mode": "not_started"}}):
                    self.assertEqual(server.measurement_status()["program_state"], program)
                    self.assertEqual(server.status()["program_state"]["mode"], mode)
                self.assertEqual(owner.details()[1], program)

    def test_old_run_cleanup_does_not_replace_a_new_run_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner = ControlWorkers()
            old = Path(temporary) / "old"
            old.mkdir()
            (old / "state.json").write_text('{"mode": "idle"}')
            (old / "feedback.json").write_text('{}')
            owner.directory = Path(temporary) / "new"
            owner.directory.mkdir()
            owner._state_file = owner.directory / "state.json"
            owner._state_file.write_text('{"mode": "starting"}')
            owner._process = Mock()
            owner._process.poll.return_value = None
            owner._finish_measurement(Mock(), old / "state.json", old)
            self.assertFalse((old / "state.json").exists())
            self.assertEqual(owner.details()[1], {"mode": "starting"})


if __name__ == "__main__":
    unittest.main()
