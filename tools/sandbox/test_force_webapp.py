"""Offline checks for attempt boundaries, force conversion, ranking and persistence."""

import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from force_webapp import Monitor, force_in_tool


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.directory.cleanup)
        self.monitor = Monitor('offline-test', 100, Path(self.directory.name))
        self.stream = io.StringIO()
        self.writer = csv.writer(self.stream)
        self.timestamp = 0

    def sample(self, force):
        self.timestamp += 1
        with self.monitor.lock:
            self.monitor.record_sample(self.timestamp, [0, 0, force], self.writer, self.stream)

    def test_attempt_boundaries_and_absolute_peak(self):
        self.sample(900)
        self.assertIsNone(self.monitor.snapshot()['sample'])
        self.monitor.action('start', ' Alice ')
        self.sample(-40)
        self.sample(25)
        self.monitor.action('stop')
        self.sample(1000)
        rows = list(csv.reader(io.StringIO(self.stream.getvalue())))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][3:5], ['Alice', '40'])
        result = self.monitor.snapshot()['results'][0]
        self.assertEqual(result['name'], 'Alice')
        self.assertEqual(result['peak_abs_tool_z_N'], 40)
        saved = json.loads((Path(self.directory.name) / 'results.json').read_text())
        self.assertEqual(saved, [result])

    def test_free_play_does_not_record_or_rank(self):
        self.monitor.action('free', enabled=True)
        self.sample(-75)
        self.assertEqual(self.monitor.snapshot()['sample']['tool_z_abs_N'], 75)
        self.assertEqual(self.stream.getvalue(), '')
        self.assertEqual(self.monitor.snapshot()['results'], [])
        with self.assertRaises(ValueError):
            self.monitor.action('start', 'Alice')
        self.monitor.action('free', enabled=False)
        self.assertIsNone(self.monitor.snapshot()['sample'])

    def test_ranking_highest_first_and_stable_ties(self):
        self.sample(0)
        for name, force in [('Alice', 10), ('Bob', -50), ('Charlie', 50)]:
            self.monitor.action('start', name)
            self.sample(force)
            self.monitor.action('stop')
        self.assertEqual([r['name'] for r in self.monitor.snapshot()['results']], ['Bob', 'Charlie', 'Alice'])

    def test_start_validation_and_stop_after_stale_data(self):
        with self.assertRaises(ValueError):
            self.monitor.action('start', 'Alice')
        self.sample(0)
        with self.assertRaises(ValueError):
            self.monitor.action('start', '  ')
        self.monitor.action('start', 'Alice')
        self.sample(20)
        with self.assertRaises(ValueError):
            self.monitor.action('free', enabled=True)
        self.monitor.updated -= 2
        self.assertFalse(self.monitor.snapshot()['fresh'])
        self.monitor.action('stop')
        self.assertEqual(len(self.monitor.results), 1)

    def test_tool_rotation(self):
        import math

        tool = force_in_tool([30, 0, 0], [0, math.pi / 2, 0])
        self.assertAlmostEqual(tool[2], 30)

    def test_full_history_survives_stop_and_resets_for_next_person(self):
        self.sample(0)
        self.monitor.action('start', 'Alice')
        for force in range(35):
            self.sample(-force)
        history = self.monitor.snapshot()['history']
        self.assertEqual(len(history), 35)
        self.assertEqual(history[0], [0, 0])
        self.assertEqual(history[-1], [34, 34])
        self.monitor.action('stop')
        self.sample(1000)
        self.assertEqual(self.monitor.snapshot()['history'], history)
        self.monitor.action('start', 'Bob')
        self.assertEqual(self.monitor.snapshot()['history'], [])
        self.assertIsNone(self.monitor.snapshot()['sample'])
        self.sample(5)
        self.assertEqual(self.monitor.snapshot()['history'], [[0, 5]])

    def test_locked_peak_on_third_person_keeps_recording_and_recovers(self):
        self.sample(0)
        for name in ('Alice', 'Bob'):
            self.monitor.action('start', name)
            self.sample(10)
            self.monitor.action('stop')
        self.monitor.action('start', 'Charlie')
        original_replace = Path.replace

        def locked_peak(source, destination):
            if destination.name == 'peak.json':
                raise PermissionError(5, 'Access is denied')
            return original_replace(source, destination)

        with patch.object(Path, 'replace', locked_peak):
            for force in (30, -50, 40):
                self.monitor.next_peak_save = 0
                self.sample(force)
            snapshot = self.monitor.snapshot()
            self.assertTrue(snapshot['fresh'])
            self.assertIsNone(snapshot['error'])
            self.assertTrue(snapshot['warning'])
            self.assertEqual(snapshot['peak_N'], 50)
            self.monitor.action('stop')
            self.assertEqual(self.monitor.results[-1]['peak_abs_tool_z_N'], 50)
        rows = list(csv.reader(io.StringIO(self.stream.getvalue())))
        self.assertEqual(len(rows), 5)
        self.monitor.next_peak_save = 0
        self.sample(0)
        self.assertIsNone(self.monitor.snapshot()['warning'])
        saved = json.loads((Path(self.directory.name) / 'peak.json').read_text())
        self.assertEqual(saved['peak_abs_tool_z_N'], 50)
        self.assertFalse(self.monitor.peak_save_pending)

    def test_stop_retries_a_locked_results_file_without_duplicate_results(self):
        self.sample(0)
        self.monitor.action('start', 'Alice')
        self.sample(25)
        original_replace = Path.replace
        denied = 0

        def temporary_lock(source, destination):
            nonlocal denied
            if destination.name == 'results.json' and denied < 2:
                denied += 1
                raise PermissionError(5, 'Access is denied')
            return original_replace(source, destination)

        with patch.object(Path, 'replace', temporary_lock), patch('force_webapp.time.sleep'):
            self.monitor.action('stop')
        self.assertEqual(denied, 2)
        self.assertEqual(len(self.monitor.results), 1)
        self.assertEqual(self.monitor.mode, 'idle')

    def test_persistent_results_lock_keeps_attempt_available_to_stop_again(self):
        self.sample(0)
        self.monitor.action('start', 'Alice')
        self.sample(25)
        with patch.object(Path, 'replace', side_effect=PermissionError(5, 'Access is denied')), patch('force_webapp.time.sleep'):
            with self.assertRaises(PermissionError):
                self.monitor.action('stop')
        self.assertEqual(self.monitor.mode, 'attempt')
        self.assertEqual(self.monitor.results, [])
        self.monitor.action('stop')
        self.assertEqual(len(self.monitor.results), 1)


if __name__ == '__main__':
    unittest.main()
