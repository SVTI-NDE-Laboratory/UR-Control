"""Automatic run logs with and without a visible terminal; no robot connection."""

from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from src.program.webapp2.control import ControlWorkers
from src.program.webapp2.measurement_worker import console_logging


class AutomaticLoggingTests(unittest.TestCase):
    def test_console_output_and_errors_are_flushed_to_run_log(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'worker.log'
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr), console_logging(path):
                print('Measurement started')
                print('Warning from acquisition', file=sys.stderr)
                self.assertIn('Measurement started', path.read_text(encoding='utf-8'))
                self.assertIn('Warning from acquisition', path.read_text(encoding='utf-8'))
            self.assertEqual(stdout.getvalue(), 'Measurement started\n')
            self.assertEqual(stderr.getvalue(), 'Warning from acquisition\n')

    def test_uncaught_error_is_logged_and_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'worker.log'
            with self.assertRaisesRegex(RuntimeError, 'Acquisition failed'):
                with console_logging(path):
                    raise RuntimeError('Acquisition failed')
            content = path.read_text(encoding='utf-8')
            self.assertIn('Traceback', content)
            self.assertIn('RuntimeError: Acquisition failed', content)

    def test_spawn_keeps_file_logging_in_both_terminal_modes(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as directory:
                workers = ControlWorkers()
                workers.directory = Path(directory)
                workers._state_file = Path(directory) / 'state.json'
                workers._kind = 'measurement'
                with patch('src.program.webapp2.control.subprocess.Popen') as process, patch('src.program.webapp2.control.threading.Thread'):
                    workers._spawn('src.program.webapp2.measurement_worker', [], terminal)
                options = process.call_args.kwargs
                if terminal:
                    self.assertIsNone(options['stdout'])
                    self.assertEqual(options['env']['UR15_WORKER_CONSOLE_LOG'], str(Path(directory).resolve() / 'worker.log'))
                else:
                    self.assertEqual(Path(options['stdout'].name), Path(directory) / 'worker.log')
                    self.assertNotIn('UR15_WORKER_CONSOLE_LOG', options['env'])


if __name__ == '__main__':
    unittest.main()
