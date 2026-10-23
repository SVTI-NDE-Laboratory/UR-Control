"""Browser connection ownership, refresh grace, and application-stop checks."""

import asyncio
import http.client
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

from src.program.webapp2.browser_session import BrowserSessions


class BrowserSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.shutdown = AsyncMock()
        self.sessions = BrowserSessions(self.shutdown, grace_seconds=.02)

    async def asyncTearDown(self):
        await self.sessions.stop()

    async def test_last_tab_disconnect_shuts_down(self):
        tab = self.sessions.connect()
        self.sessions.disconnect(tab)
        await asyncio.sleep(.05)
        self.shutdown.assert_awaited_once()

    async def test_refresh_reconnect_cancels_shutdown(self):
        tab = self.sessions.connect()
        self.sessions.disconnect(tab)
        replacement = self.sessions.connect()
        await asyncio.sleep(.05)
        self.shutdown.assert_not_awaited()
        self.sessions.disconnect(replacement)
        await asyncio.sleep(.05)
        self.shutdown.assert_awaited_once()

    async def test_closing_one_of_two_tabs_keeps_app_running(self):
        first, second = self.sessions.connect(), self.sessions.connect()
        self.sessions.disconnect(first)
        await asyncio.sleep(.05)
        self.shutdown.assert_not_awaited()
        self.sessions.disconnect(second)
        await asyncio.sleep(.05)
        self.shutdown.assert_awaited_once()

    async def test_background_tab_and_no_browser_startup_do_not_expire(self):
        await asyncio.sleep(.05)
        self.shutdown.assert_not_awaited()
        self.sessions.connect()
        await asyncio.sleep(.05)
        self.shutdown.assert_not_awaited()

    async def test_lifespan_stop_cancels_pending_browser_shutdown(self):
        tab = self.sessions.connect()
        self.sessions.disconnect(tab)
        await self.sessions.stop()
        await asyncio.sleep(.05)
        self.shutdown.assert_not_awaited()

    async def test_shutdown_failure_is_logged_and_rejects_new_tabs(self):
        self.shutdown.side_effect = RuntimeError('Robot stop could not be confirmed')
        tab = self.sessions.connect()
        with patch('src.program.webapp2.browser_session.logger') as logger:
            self.sessions.disconnect(tab)
            await asyncio.sleep(.05)
            logger.exception.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, 'closing'):
            self.sessions.connect()

    async def test_closing_app_rejects_new_worker_commands(self):
        import httpx
        from src.program.webapp2 import server
        with patch.object(server.api.state, 'browser_sessions', Mock(closing=True), create=True), \
                patch.object(server.workers, 'start_flexible') as start:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api),
                                         base_url='http://test') as client:
                response = await client.post('/api/flexible/start')
        self.assertEqual(response.status_code, 409)
        start.assert_not_called()


class AppCloseTests(unittest.TestCase):
    def test_close_stops_worker_and_exits_even_if_hardware_stop_fails(self):
        from src.program.webapp2 import server
        host = Mock(should_exit=False)
        workers = Mock()
        workers.snapshot.return_value = {'running': True}
        workers.stop.side_effect = RuntimeError('Robot stop could not be confirmed')
        with patch.object(server, 'workers', workers), \
                patch.object(server.api.state, 'uvicorn_server', host, create=True):
            with self.assertRaisesRegex(RuntimeError, 'Robot stop'):
                server.close_app()
        workers.stop.assert_called_once()
        self.assertTrue(host.should_exit)


class BrowserShutdownProcessTests(unittest.TestCase):
    def test_refresh_multiple_tabs_and_last_close_through_real_http(self):
        """Launch without opening a browser or connecting to robot hardware."""
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            from src.program.webapp2.profile import initialize
            initialize(folder)
            environment = os.environ.copy()
            environment.pop('UR15_WEBAPP_ACTIVE_PROFILE', None)
            process = subprocess.Popen([sys.executable, '-u', str(root / 'tools/webapp2.py'),
                                        '--data-dir', folder, '--no-browser'], cwd=root,
                                       env=environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            lines = queue.Queue()
            connections = []

            def read_output():
                for line in process.stdout:
                    lines.put(line)
                lines.put(None)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()
            try:
                while True:
                    line = lines.get(timeout=15)
                    self.assertIsNotNone(line, 'App exited before publishing its URL')
                    if line.startswith('RTM Cobot Studio: '):
                        url = urlsplit(line.split(': ', 1)[1].strip())
                        break

                def open_tab():
                    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
                    connections.append(connection)
                    connection.request('GET', '/api/browser-session')
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn('text/event-stream', response.getheader('Content-Type'))
                    self.assertEqual(response.readline(), b'retry: 1000\n')
                    return connection, response

                def close_tab(tab):
                    connection, response = tab
                    response.close()
                    connection.close()

                # Replacing the last tab during refresh cancels the pending exit.
                first = open_tab()
                close_tab(first)
                time.sleep(.2)
                first = open_tab()
                time.sleep(3.3)
                self.assertIsNone(process.poll(), 'Refresh shut down the application')

                # A remaining tab keeps the application alive.
                second = open_tab()
                close_tab(first)
                time.sleep(3.3)
                self.assertIsNone(process.poll(), 'Closing one of two tabs shut down the application')

                # Closing the final connection exits the launcher on its own.
                close_tab(second)
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                for connection in connections:
                    connection.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                reader.join(timeout=2)
                process.stdout.close()


if __name__ == '__main__':
    unittest.main()
