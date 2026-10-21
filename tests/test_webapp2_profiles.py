"""Profile persistence, restart and worker inheritance without robot hardware."""

import os
import json
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from src.program.webapp2.profile import (
    ROOT, initialize, load_profile, read_object, select_profile, write_object,
    application_directory, prepare_startup, change_data_directory, display_path,
    default_directory, migrate_legacy_directory,
)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name).resolve()
        self.profile = load_profile(self.data)

    def alternative(self):
        target = self.data / "other installation"
        shutil.copytree(self.profile.path.parent, target)
        path = target / "app_config.json"
        values = read_object(path)
        values["robot_ip"] = "192.0.2.42"
        write_object(path, values)
        return path

    def test_first_launch_seeds_files_and_preserves_user_changes(self):
        self.assertNotIn("measurement_mira_defaults", self.profile.values)
        self.assertFalse((self.profile.path.parent / "measurement_mira.json").exists())
        defaults = self.profile.paths["measurement_defaults"]
        config = read_object(defaults)
        config["measurement"]["holding_force"] = 240
        write_object(defaults, config)
        before = defaults.read_bytes()
        initialize(self.data)
        self.assertEqual(defaults.read_bytes(), before)
        self.assertTrue((self.data / "runtime").is_dir())
        self.assertTrue((self.profile.paths["robot_programs_directory"] / "apply_force.script").is_file())

    def test_existing_profile_does_not_require_its_old_mira_file(self):
        values = read_object(self.profile.path)
        values["measurement_mira_defaults"] = "missing_obsolete_mira.json"
        write_object(self.profile.path, values)
        restarted = load_profile(self.data)
        self.assertNotIn("measurement_mira_defaults", restarted.paths)

    def test_relative_profile_paths_survive_copy_and_restart(self):
        selected = self.alternative()
        select_profile(self.profile, str(selected.relative_to(self.data)))
        restarted = load_profile(self.data)
        self.assertEqual(restarted.path, selected)
        self.assertEqual(restarted.values["robot_ip"], "192.0.2.42")
        self.assertEqual(restarted.paths["measurement_defaults"].parent, selected.parent)
        self.assertEqual(self.profile.values["robot_ip"], "192.168.3.10")

    def test_invalid_profile_cannot_replace_preferences(self):
        selected = self.alternative()
        values = read_object(selected)
        values["measurement_defaults"] = "missing.json"
        write_object(selected, values)
        before = self.profile.preferences_path.read_bytes()
        with self.assertRaises(OSError):
            select_profile(self.profile, str(selected))
        self.assertEqual(self.profile.preferences_path.read_bytes(), before)

    def test_invalid_measurement_geometry_and_ui_defaults_are_rejected(self):
        selected = self.alternative()
        values = read_object(selected)
        values["ui_defaults"]["joint_speed"] = 1
        write_object(selected, values)
        with self.assertRaisesRegex(ValueError, "joint_speed"):
            select_profile(self.profile, str(selected))
        values["ui_defaults"]["joint_speed"] = 0.05
        write_object(selected, values)
        measurement_path = selected.parent / "measurement_default.json"
        measurement = read_object(measurement_path)
        measurement["measurement"]["max_displacement"] = -1
        write_object(measurement_path, measurement)
        with self.assertRaisesRegex(ValueError, "displacement"):
            select_profile(self.profile, str(selected))

    def test_worker_keeps_active_profile_after_preferences_and_file_change(self):
        environment = self.profile.worker_environment()
        select_profile(self.profile, str(self.alternative()))
        values = read_object(self.profile.path)
        values["robot_ip"] = "192.0.2.99"
        write_object(self.profile.path, values)
        with patch.dict(os.environ, environment, clear=True):
            worker = load_profile()
        self.assertEqual(worker.path, self.profile.path)
        self.assertEqual(worker.values["robot_ip"], "192.168.3.10")

    def test_fresh_process_reads_selected_profile_before_importing_app(self):
        selected = self.alternative()
        select_profile(self.profile, str(selected))
        environment = os.environ.copy()
        environment.pop("UR15_WEBAPP_ACTIVE_PROFILE", None)
        environment["UR15_WEBAPP_DATA_DIR"] = str(self.data)
        environment["UR15_WEBAPP_LOCATION_FILE"] = str(self.data / "location.json")
        script = (
            "from src.program.webapp2 import server; "
            "from src.program.webapp2 import flexible_worker; "
            "import measurement_config; from webapp import launcher, worker_manager; "
            "from src.program.commands import run_measurement_sequence as sequence; "
            "assert server.PROFILE.values['robot_ip'] == '192.0.2.42'; "
            "assert launcher.ROBOT_IP == worker_manager.ROBOT_IP == sequence.ROBOT_IP == flexible_worker.flexible.ROBOT_IP == '192.0.2.42'; "
            "assert measurement_config.DEFAULT_CONFIG_FILE == server.PROFILE.paths['measurement_defaults']; "
            "assert server.legacy.state.output_directory == server.PROFILE.paths['results_directory']; "
            "print('profile startup OK')"
        )
        result = subprocess.run([sys.executable, "-c", script], env=environment,
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("profile startup OK", result.stdout)

    def test_invalid_preferences_fail_startup_without_silent_fallback(self):
        write_object(self.profile.preferences_path, {"schema_version": 1, "configuration_path": "missing.json"})
        result = subprocess.run([sys.executable, str(ROOT / "tools/webapp2.py"),
                                 "--data-dir", str(self.data), "--check-config"],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertIn("startup failed", result.stderr)
        self.assertIn("missing.json", result.stderr)

    def test_launcher_serves_selected_profile_and_closes(self):
        selected = self.alternative()
        select_profile(self.profile, str(selected))
        environment = os.environ.copy()
        environment.pop("UR15_WEBAPP_ACTIVE_PROFILE", None)
        process = subprocess.Popen([sys.executable, "-u", str(ROOT / "tools/webapp2.py"),
                                    "--data-dir", str(self.data), "--no-browser"],
                                   cwd=ROOT, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True)
        lines = queue.Queue()

        def read_output():
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            while True:
                line = lines.get(timeout=15)
                self.assertIsNotNone(line, "Launcher exited before publishing its URL.")
                if line.startswith("RTM Cobot Studio: "):
                    base = line.split(": ", 1)[1].strip().removesuffix("/manual")
                    break
            with urlopen(base + "/api/settings", timeout=10) as response:
                settings = json.load(response)
            self.assertEqual(Path(settings["active_configuration_path"]), selected)
            self.assertEqual(settings["robot_ip"], "192.0.2.42")
            with urlopen(Request(base + "/api/close", data=b"{}",
                                 headers={"Content-Type": "application/json"}), timeout=10) as response:
                self.assertTrue(json.load(response)["closed"])
            self.assertEqual(process.wait(timeout=10), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdout.close()


class SettingsApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_settings_validate_save_and_block_changes_during_actions(self):
        import httpx
        from src.program.webapp2 import server
        with tempfile.TemporaryDirectory() as directory:
            profile = load_profile(Path(directory))
            with patch.object(server, "PROFILE", profile), patch.object(server.workers, "snapshot", return_value={"running": False}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test") as client:
                    current = await client.get("/api/settings")
                    self.assertEqual(current.json()["active_configuration_path"], str(profile.path))
                    self.assertEqual(current.json()["display_paths"]["app_config"], str(Path("profiles/default/app_config.json")))
                    missing = await client.post("/api/settings", json={"configuration_path": "missing.json"})
                    self.assertEqual(missing.status_code, 400)
                    saved = await client.post("/api/settings", json={"configuration_path": str(profile.path)})
                    self.assertEqual(saved.status_code, 200)
                    self.assertTrue(saved.json()["restart_required"])
                    with patch.object(server.workers, "snapshot", return_value={"running": True}):
                        blocked = await client.post("/api/settings", json={"configuration_path": str(profile.path)})
                    self.assertEqual(blocked.status_code, 409)

    async def test_local_data_picker_cancel_and_busy_do_not_change_settings(self):
        import httpx
        from src.program.webapp2 import server
        with patch.object(server.workers, "snapshot", return_value={"running": False}), patch.object(server, "choose_local_data", return_value=None) as chooser:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test") as client:
                cancelled = await client.post("/api/settings/local-data", json={})
                self.assertTrue(cancelled.json()["cancelled"])
                chooser.assert_called_once()
                chooser.reset_mock()
                with patch.object(server.workers, "snapshot", return_value={"running": True}):
                    blocked = await client.post("/api/settings/local-data", json={})
                self.assertEqual(blocked.status_code, 409)
                chooser.assert_not_called()


class LocalDataLocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.data = self.root / "current"
        self.locator = self.root / "launcher/location.json"
        environment = patch.dict(os.environ, {"UR15_WEBAPP_DATA_DIR": str(self.data),
                                             "UR15_WEBAPP_LOCATION_FILE": str(self.locator)})
        environment.start()
        self.addCleanup(environment.stop)

    def test_missing_data_opens_picker_and_remembers_selection(self):
        selected = self.root / "selected"
        with patch("src.program.webapp2.dialogs.choose_local_data", return_value=selected) as chooser:
            prepare_startup()
        chooser.assert_called_once_with(missing=True)
        self.assertEqual(application_directory(), selected)
        self.assertTrue((selected / "preferences.json").is_file())
        with patch("src.program.webapp2.dialogs.choose_local_data") as chooser:
            prepare_startup()
        chooser.assert_not_called()

    def test_missing_saved_location_cancel_does_not_recreate_data(self):
        missing = self.root / "lost"
        write_object(self.locator, {"data_directory": str(missing)})
        before = self.locator.read_bytes()
        with patch("src.program.webapp2.dialogs.choose_local_data", return_value=None):
            with self.assertRaisesRegex(ValueError, "cancelled"):
                prepare_startup()
        self.assertFalse(missing.exists())
        self.assertEqual(self.locator.read_bytes(), before)

    def test_copy_rebases_absolute_paths_preserves_defaults_and_persists_location(self):
        profile = load_profile(self.data)
        values = read_object(profile.path)
        values["routine_file"] = str(profile.paths["routine_file"])
        values["routine_scripts_directory"] = str(profile.paths["routine_scripts_directory"])
        write_object(profile.path, values)
        select_profile(profile, str(profile.path))
        destination = self.root / "new base"
        candidate = change_data_directory(profile, destination)
        self.assertEqual(application_directory(), destination)
        self.assertEqual(candidate.path, destination / "profiles/default/app_config.json")
        self.assertEqual(candidate.paths["routine_file"], destination / "profiles/default/routines/routine_bam_at_svti.json")
        self.assertEqual(candidate.paths["routine_scripts_directory"], destination / "profiles/default/routine_scripts")
        self.assertEqual(candidate.paths["measurement_defaults"].read_bytes(), profile.paths["measurement_defaults"].read_bytes())
        self.assertTrue(profile.path.exists())
        self.assertEqual(load_profile().data_dir, destination)

    def test_existing_data_is_selected_without_copying_over_it(self):
        profile = load_profile(self.data)
        target = load_profile(self.root / "other")
        before = target.path.read_bytes()
        change_data_directory(profile, target.data_dir)
        self.assertEqual(application_directory(), target.data_dir)
        self.assertEqual(target.path.read_bytes(), before)

    def test_nonempty_and_nested_destinations_leave_locator_unchanged(self):
        profile = load_profile(self.data)
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "unrelated.txt").write_text("keep")
        for target in (occupied, self.data / "nested", self.root):
            with self.assertRaises(ValueError):
                change_data_directory(profile, target)
        self.assertFalse(self.locator.exists())
        self.assertEqual((occupied / "unrelated.txt").read_text(), "keep")

    def test_invalid_existing_profile_does_not_replace_saved_location(self):
        profile = load_profile(self.data)
        destination = self.root / "invalid"
        write_object(destination / "preferences.json", {"schema_version": 1, "configuration_path": "missing.json"})
        with self.assertRaises(OSError):
            change_data_directory(profile, destination)
        self.assertFalse(self.locator.exists())

    def test_display_paths_are_relative_to_local_data(self):
        self.assertEqual(display_path(self.data / "profiles/default/app_config.json", self.data),
                         str(Path("profiles/default/app_config.json")))


class BrandedLocalDataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.old = self.root / "UR15 WebApp"
        self.new = self.root / "RTM Cobot Studio"

    def test_default_directory_uses_the_product_name(self):
        self.assertEqual(default_directory(), self.new)

    def test_migration_preserves_defaults_results_and_rebases_absolute_internal_paths(self):
        profile = load_profile(self.old)
        values = dict(profile.values)
        for key, path in profile.paths.items():
            values[key] = str(path)
        write_object(profile.path, values)
        write_object(profile.preferences_path, {"schema_version": 1, "configuration_path": str(profile.path)})
        write_object(self.old / 'location.json', {'data_directory': str(self.old)})
        (self.old / 'results' / 'sample').mkdir(parents=True)
        result = self.old / 'results/sample/result.txt'
        result.write_bytes(b'original measurement data')
        defaults = profile.paths['measurement_defaults']
        values = read_object(defaults)
        values['measurement']['holding_force'] = 250
        write_object(defaults, values)
        original_preferences = profile.preferences_path.read_bytes()
        migrated = load_profile()
        self.assertEqual(migrated.data_dir, self.new)
        self.assertEqual(migrated.path, self.new / 'profiles/default/app_config.json')
        self.assertEqual(migrated.paths['results_directory'], self.new / 'results')
        self.assertEqual(migrated.paths['measurement_defaults'].read_bytes(), defaults.read_bytes())
        self.assertEqual((self.new / 'results/sample/result.txt').read_bytes(), result.read_bytes())
        self.assertEqual(profile.preferences_path.read_bytes(), original_preferences)
        self.assertEqual(application_directory(), self.new)
        self.assertEqual(list(self.root.glob('.rtm-cobot-studio-*')), [])

    def test_migration_keeps_an_existing_custom_selection(self):
        custom = load_profile(self.root / 'custom data')
        write_object(self.old / 'location.json', {'data_directory': str(custom.data_dir)})
        migrate_legacy_directory()
        self.assertEqual(application_directory(), custom.data_dir)
        self.assertFalse((self.new / 'preferences.json').exists())
        self.assertEqual(load_profile().data_dir, custom.data_dir)

    def test_missing_custom_selection_is_not_replaced_with_blank_defaults(self):
        missing = self.root / 'missing data'
        write_object(self.old / 'location.json', {'data_directory': str(missing)})
        with patch('src.program.webapp2.dialogs.choose_local_data', return_value=None) as chooser:
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                prepare_startup()
        chooser.assert_called_once_with(missing=True)
        self.assertEqual(application_directory(), missing)
        self.assertFalse(missing.exists())

    def test_existing_branded_data_is_never_overwritten(self):
        old = load_profile(self.old)
        current = load_profile(self.new)
        values = read_object(current.paths['measurement_defaults'])
        values['measurement']['holding_force'] = 260
        write_object(current.paths['measurement_defaults'], values)
        expected = current.paths['measurement_defaults'].read_bytes()
        migrate_legacy_directory()
        self.assertEqual(load_profile().paths['measurement_defaults'].read_bytes(), expected)
        self.assertNotEqual(expected, old.paths['measurement_defaults'].read_bytes())

    def test_explicit_data_and_locator_overrides_disable_automatic_migration(self):
        load_profile(self.old)
        for key in ('UR15_WEBAPP_DATA_DIR', 'UR15_WEBAPP_LOCATION_FILE'):
            with patch.dict(os.environ, {key: str(self.root / 'explicit')}):
                migrate_legacy_directory()
            self.assertFalse(self.new.exists())

    def test_failed_copy_never_publishes_partial_data(self):
        load_profile(self.old)
        with patch('src.program.webapp2.profile.copy_local_data', side_effect=OSError('copy failed')):
            with self.assertRaisesRegex(OSError, 'copy failed'):
                migrate_legacy_directory()
        self.assertFalse(self.new.exists())
        self.assertTrue((self.old / 'preferences.json').is_file())
        self.assertEqual(list(self.root.glob('.rtm-cobot-studio-*')), [])
