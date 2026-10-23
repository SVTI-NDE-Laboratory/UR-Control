"""Measurement snapshots tolerate transient locks without hiding real failures."""

import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/measurement"))

import atomic_json
from measurement_state import write_state
from measurement_plan import record_measurement_result, write_measurement_plan


class MeasurementSnapshotTests(unittest.TestCase):
    def test_state_retries_a_temporary_destination_lock(self):
        replace = Path.replace
        attempts = []
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            write_state(target, {"measurement_index": 1})

            def temporarily_locked(staging, destination):
                attempts.append(staging)
                if len(attempts) == 1:
                    self.assertEqual(json.loads(target.read_text()), {"measurement_index": 1})
                    raise PermissionError("Web reader briefly holds the file")
                return replace(staging, destination)

            with patch.object(Path, "replace", new=temporarily_locked):
                write_state(str(target), {"measurement_index": 2})
            self.assertEqual(len(attempts), 2)
            self.assertEqual(json.loads(target.read_text()), {"measurement_index": 2})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_permanent_lock_preserves_previous_state_and_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            write_state(target, {"measurement_index": 1})
            with patch.object(Path, "replace", side_effect=PermissionError("Locked")), patch.object(atomic_json.time, "monotonic", side_effect=[0, 1]):
                with self.assertRaises(PermissionError):
                    write_state(target, {"measurement_index": 2})
            self.assertEqual(json.loads(target.read_text()), {"measurement_index": 1})
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_concurrent_state_writers_have_separate_staging_files(self):
        replace = Path.replace
        staging_paths = []

        def capture(staging, destination):
            staging_paths.append(staging)
            return replace(staging, destination)

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "state.json"
            with patch.object(Path, "replace", new=capture), ThreadPoolExecutor(max_workers=4) as executor:
                list(executor.map(lambda index: write_state(target, {"measurement_index": index}), range(16)))
            self.assertEqual(len(set(staging_paths)), 16)
            self.assertIn(json.loads(target.read_text())["measurement_index"], range(16))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_plan_and_result_updates_retry_destination_lock(self):
        plan = {"points": [{"point_number": 1, "data": {"status": None}}]}
        replace = Path.replace
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "measurement_results.json"
            for operation in (lambda: write_measurement_plan(target, {}),
                              lambda: record_measurement_result(target, 1, "measured", "test")):
                attempts = []

                def temporarily_locked(staging, destination):
                    attempts.append(staging)
                    if len(attempts) == 1:
                        raise PermissionError("Web reader briefly holds plan")
                    return replace(staging, destination)

                with patch("measurement_plan.create_measurement_plan", return_value=plan), patch.object(Path, "replace", new=temporarily_locked):
                    operation()
                self.assertEqual(len(attempts), 2)
            saved = json.loads(target.read_text())
            self.assertEqual(saved["points"][0]["data"]["status"], "measured")
            self.assertEqual(saved["points"][0]["data"]["timestamp"], "test")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
