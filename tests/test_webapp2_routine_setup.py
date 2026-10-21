"""Routine creation, selection and API exclusion without robot connections."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.program.webapp2.profile import load_profile, read_object, write_object
from src.program.webapp2.routine_setup import RoutineCreation, create_routine, select_routine, creation_defaults


def creation(**overrides):
    lines = []
    coordinates = {"p_start_h": [0, 0, .1, 0, 0, 0], "p_start_l": [0, 0, 0, 0, 0, 0],
                   "p_end_h": [1, 0, .1, 0, 0, 0], "p_end_l": [1, 0, 0, 0, 0, 0]}
    for name in ["Home", "approach", "exit", *coordinates]:
        lines.append(f"global {name}_q=[0, 0, 0, 0, 0, 0]")
        if name in coordinates:
            lines.append(f"global {name}_p=p{coordinates[name]}")
    return RoutineCreation(**{
        "filename": "new_routine.json", "script": "\n".join(lines),
        "home_to_start": ["Home", "approach", "p_start_h"],
        "end_to_home": ["p_end_h", "exit", "Home"], **overrides})


class RoutineSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = load_profile(Path(self.temp.name))
        self.directory = self.profile.paths["routine_file"].parent

    def test_creation_generates_all_routes_and_exact_endpoints_without_selecting(self):
        before = self.profile.path.read_bytes()
        target = create_routine(self.profile, creation())
        data = read_object(target)
        routes = {routine["name"]: routine["steps"] for routine in data["routines"]}
        self.assertEqual(set(routes), {"home_to_start", "start_to_home", "home_to_end", "end_to_home"})
        self.assertEqual([step["waypoint"] for step in routes["start_to_home"]], ["p_start_h", "approach", "Home"])
        self.assertEqual([step["waypoint"] for step in routes["home_to_end"]], ["Home", "exit", "p_end_h"])
        self.assertIn("p_start_l", data["waypoints"])
        self.assertIn("p_end_l", data["waypoints"])
        for steps in routes.values():
            self.assertEqual(steps[0]["motion"]["blend_radius"], 0)
            self.assertEqual(steps[-1]["motion"]["blend_radius"], 0)
            self.assertEqual(steps[1]["motion"], {"type": "j", "speed": 2, "acceleration": .4, "blend_radius": 5})
        self.assertEqual(self.profile.path.read_bytes(), before)
        self.assertFalse(list((self.profile.data_dir / "runtime").iterdir()))

    def test_selection_persists_for_restart_without_changing_active_snapshot(self):
        target = create_routine(self.profile, creation(filename="created without suffix"))
        selected = select_routine(self.profile, target.name)
        self.assertEqual(selected, target)
        self.assertEqual(load_profile(self.profile.data_dir).paths["routine_file"], target)
        self.assertNotEqual(self.profile.paths["routine_file"], target)

    def test_missing_waypoint_never_creates_partial_output(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            create_routine(self.profile, creation(home_to_start=["Home", "Missing", "p_start_h"]))
        self.assertFalse((self.directory / "new_routine.json").exists())
        self.assertFalse(list((self.profile.data_dir / "runtime").iterdir()))

    def test_existing_output_and_active_file_cannot_be_overwritten(self):
        before = self.profile.paths["routine_file"].read_bytes()
        with self.assertRaises(FileExistsError):
            create_routine(self.profile, creation(filename=self.profile.paths["routine_file"].name))
        self.assertEqual(self.profile.paths["routine_file"].read_bytes(), before)

    def test_path_traversal_and_windows_reserved_names_are_rejected(self):
        for name in ("../outside.json", "C:/outside.json", "CON.json", "file?.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                create_routine(self.profile, creation(filename=name))
            with self.subTest(selection=name), self.assertRaises(ValueError):
                select_routine(self.profile, name)

    def test_incompatible_measurement_file_does_not_replace_selection(self):
        before = self.profile.path.read_bytes()
        invalid = self.directory / "invalid.json"
        write_object(invalid, {"waypoints": {}, "routines": []})
        with self.assertRaises(ValueError):
            select_routine(self.profile, invalid.name)
        self.assertEqual(self.profile.path.read_bytes(), before)

    def test_joint_steps_require_joint_targets(self):
        request = creation()
        request.script = request.script.replace("global approach_q=[0, 0, 0, 0, 0, 0]", "global approach_p=p[0, 0, 0, 0, 0, 0]")
        with self.assertRaisesRegex(ValueError, "no q target"):
            create_routine(self.profile, request)
        self.assertFalse((self.directory / request.filename).exists())

    def test_measurement_waypoints_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError, "fixed"):
            create_routine(self.profile, creation(additional_waypoints=["Other"]))
        self.assertFalse((self.directory / "new_routine.json").exists())

    def test_form_defaults_follow_active_routine_and_measurement_points(self):
        defaults = creation_defaults(self.profile)
        routes = {routine["name"]: routine for routine in read_object(self.profile.paths["routine_file"])["routines"]}
        self.assertEqual(defaults["home_to_start"], [step["waypoint"] for step in routes["home_to_start"]["steps"]])
        self.assertEqual(defaults["end_to_home"], [step["waypoint"] for step in routes["end_to_home"]["steps"]])
        self.assertEqual(defaults["measurement_waypoints"], ["p_start_l", "p_end_l"])

    def test_older_profiles_get_seeded_scripts_and_configurable_directory(self):
        values = read_object(self.profile.path)
        values.pop("routine_scripts_directory")
        write_object(self.profile.path, values)
        migrated = load_profile(self.profile.data_dir)
        self.assertTrue(list(migrated.paths["routine_scripts_directory"].glob("*.script")))
        self.assertEqual(read_object(migrated.path)["routine_scripts_directory"], "routine_scripts")
        custom = self.profile.data_dir / "custom script library"
        custom.mkdir()
        values["routine_scripts_directory"] = str(custom)
        write_object(self.profile.path, values)
        custom_profile = load_profile(self.profile.data_dir)
        self.assertEqual(custom_profile.paths["routine_scripts_directory"], custom)
        self.assertFalse(list(custom.iterdir()))


class RoutineApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_script_chooser_starts_in_configured_directory_and_can_cancel(self):
        import httpx
        from src.program.webapp2 import server
        with tempfile.TemporaryDirectory() as directory:
            profile = load_profile(Path(directory))
            source = next(profile.paths["routine_scripts_directory"].glob("*.script"))
            with patch.object(server, "PROFILE", profile), patch.object(server.workers, "snapshot", return_value={"running": False}), patch.object(server, "choose_routine_script", return_value=None) as chooser:
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test") as client:
                    cancelled = await client.post("/api/settings/routines/script", json={})
                    self.assertTrue(cancelled.json()["cancelled"])
                    chooser.assert_called_once_with(profile.paths["routine_scripts_directory"])
                    chooser.return_value = source
                    chosen = await client.post("/api/settings/routines/script", json={})
                    self.assertEqual(chosen.status_code, 200, chosen.text)
                    self.assertEqual(chosen.json()["filename"], source.name)
                    self.assertTrue(chosen.json()["script"])
                    chooser.reset_mock()
                    with patch.object(server.workers, "snapshot", return_value={"running": True}):
                        blocked = await client.post("/api/settings/routines/script", json={})
                    self.assertEqual(blocked.status_code, 409)
                    chooser.assert_not_called()

    async def test_list_create_select_and_busy_interlock(self):
        import httpx
        from src.program.webapp2 import server
        with tempfile.TemporaryDirectory() as directory:
            profile = load_profile(Path(directory))
            with patch.object(server, "PROFILE", profile), patch.object(server.workers, "snapshot", return_value={"running": False}):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.api), base_url="http://test") as client:
                    created = await client.post("/api/settings/routines/create", json=creation().model_dump())
                    self.assertEqual(created.status_code, 200, created.text)
                    listing = (await client.get("/api/settings/routines")).json()
                    self.assertIn("new_routine.json", listing["files"])
                    self.assertNotEqual(listing["selected"], "new_routine.json")
                    with patch.object(server.workers, "snapshot", return_value={"running": True}):
                        for endpoint, payload in (("select", {"filename": "new_routine.json"}), ("create", creation(filename="blocked.json").model_dump())):
                            response = await client.post("/api/settings/routines/" + endpoint, json=payload)
                            self.assertEqual(response.status_code, 409)
                    selected = await client.post("/api/settings/routines/select", json={"filename": "new_routine.json"})
                    self.assertEqual(selected.status_code, 200, selected.text)
                    self.assertTrue(selected.json()["restart_required"])
                    self.assertEqual(load_profile(profile.data_dir).paths["routine_file"].name, "new_routine.json")
                    bad = await client.post("/api/settings/routines/select", json={"filename": "../outside.json"})
                    self.assertEqual(bad.status_code, 400)
