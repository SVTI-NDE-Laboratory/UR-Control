"""Folder selection and atomic creation without robot hardware or real results."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from src.program.webapp2 import server


class MeasurementFolderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.results = Path(temporary.name).resolve() / "configured-results"
        self.workers = Mock()
        self.workers.snapshot.return_value = {"running": False}
        self.workers.start_measurement.return_value = {"running": True, "kind": "measurement"}
        old_config = server.legacy.state.get_config()
        old_session = server.legacy.state.get_session()
        self.addCleanup(server.legacy.state.set_config, old_config) if old_config else self.addCleanup(server.legacy.state.clear_config)
        self.addCleanup(server.legacy.state.set_session, *old_session)
        server.legacy.state.set_config({"measurement": {}})
        self.preflight = Mock()
        for item in (
            patch.object(server, "PROFILE", SimpleNamespace(paths={"results_directory": self.results})),
            patch.object(server, "workers", self.workers),
            patch.object(server.legacy, "assert_safe_start_position", self.preflight),
            patch.object(server.legacy, "read_default_program_path", return_value="installed.urp"),
            patch.object(server.legacy, "line_geometry", return_value={}),
            patch.object(server.legacy, "line_scope_warning", return_value=None),
            patch.object(server.legacy, "create_session_identity", return_value=("2026-10-21_14-30-00-123456", "2026-10-21T14:30:00")),
        ):
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def test_manual_folder_is_created_only_when_starting_inside_configured_results(self):
        selection = {"automatic_folder_name": False, "folder_name": "Sample 123"}
        checked = await self.client.post('/api/measurement/folder', json=selection)
        self.assertEqual(checked.status_code, 200)
        self.assertFalse(self.results.exists())
        response = await self.client.post('/api/measurement/start', json=selection)
        self.assertEqual(response.status_code, 200, response.text)
        folder = self.results / "Sample 123"
        self.assertEqual(response.json()['output_directory'], str(folder))
        session = json.loads((folder / 'session.json').read_text())
        self.assertFalse(session['automatic_session_folder'])
        self.assertEqual(session['folder_name'], "Sample 123")
        self.assertEqual(self.workers.start_measurement.call_args.args[1], folder)
        self.assertEqual(self.workers.start_measurement.call_args.args[0]['measurement']['program_path'], 'installed.urp')

    async def test_automatic_name_is_generated_at_start_and_matches_actual_folder(self):
        response = await self.client.post('/api/measurement/start', json={})
        self.assertEqual(response.status_code, 200, response.text)
        name = response.json()['folder_name']
        self.assertEqual(name, response.json()['session_id'])
        self.assertEqual(name, "2026-10-21_14-30-00-123456")
        session = json.loads((self.results / name / 'session.json').read_text())
        self.assertTrue(session['automatic_session_folder'])

    async def test_existing_folder_or_file_is_never_overwritten(self):
        folder = self.results / "existing"
        folder.mkdir(parents=True)
        sentinel = folder / 'session.json'
        sentinel.write_bytes(b'original results')
        (self.results / "file").write_bytes(b'original file')
        for name in ("existing", "file"):
            selection = {"automatic_folder_name": False, "folder_name": name}
            for endpoint in ('/api/measurement/folder', '/api/measurement/start'):
                response = await self.client.post(endpoint, json=selection)
                self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(sentinel.read_bytes(), b'original results')
        self.assertEqual((self.results / "file").read_bytes(), b'original file')
        self.preflight.assert_not_called()
        self.workers.start_measurement.assert_not_called()

    async def test_racing_folder_creation_is_rejected_before_session_files_are_written(self):
        folder = self.results / "race"
        def create_during_preflight(_):
            folder.mkdir(parents=True)
            (folder / 'session.json').write_bytes(b'created by another process')
        self.preflight.side_effect = create_during_preflight
        response = await self.client.post('/api/measurement/start', json={"automatic_folder_name": False, "folder_name": "race"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((folder / 'session.json').read_bytes(), b'created by another process')
        self.workers.start_measurement.assert_not_called()

    async def test_invalid_names_cannot_escape_results_or_use_windows_reserved_names(self):
        for name in ('', '.', '..', '../escape', 'nested/folder', 'nested\\folder', 'C:\\escape', 'CON', 'nul.txt', 'LPT1', 'bad:name', 'trailing.', ' leading', 'trailing ', 'bad\x00name'):
            response = await self.client.post('/api/measurement/folder', json={"automatic_folder_name": False, "folder_name": name})
            self.assertEqual(response.status_code, 422, (name, response.text))
        self.assertFalse(self.results.exists())
        response = await self.client.post('/api/measurement/start', json={"output_directory": str(self.results.parent)})
        self.assertEqual(response.status_code, 422)
        self.preflight.assert_not_called()

    async def test_failed_robot_preflight_creates_no_measurement_folder(self):
        self.preflight.side_effect = ValueError('Robot is not at Home')
        response = await self.client.post('/api/measurement/start', json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.results.exists())
        self.workers.start_measurement.assert_not_called()

    async def test_outside_line_requires_confirmation_before_preflight_or_folder_creation(self):
        with patch.object(server.legacy, 'line_scope_warning', return_value='Measurements outside the taught line'):
            response = await self.client.post('/api/measurement/start', json={})
            self.assertEqual(response.status_code, 409)
            self.preflight.assert_not_called()
            self.assertFalse(self.results.exists())
            response = await self.client.post('/api/measurement/start', json={'outside_line_confirmed': True})
            self.assertEqual(response.status_code, 200, response.text)
            self.preflight.assert_called_once()

    async def test_automatic_name_collision_cannot_reuse_a_previous_run(self):
        first = await self.client.post('/api/measurement/start', json={})
        self.assertEqual(first.status_code, 200, first.text)
        file = Path(first.json()['output_directory']) / 'session.json'
        original = file.read_bytes()
        second = await self.client.post('/api/measurement/start', json={})
        self.assertEqual(second.status_code, 409)
        self.assertEqual(file.read_bytes(), original)
        self.workers.start_measurement.assert_called_once()
