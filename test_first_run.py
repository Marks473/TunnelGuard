from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from desktop_control import DesktopGuard, amnezia_ui, find_app, valid_app_path
from guard import Evidence, GuardDenied
from settings import Settings, load_settings, save_settings
from windows_probe import Route, probe_windows


class FirstRunTests(unittest.TestCase):
    def test_unconfigured_target_fails_closed_before_probing_or_starting(self):
        self.assertIsNone(Settings().target_ip)
        self.assertIsNone(Settings().vpn_server_ip)
        route = Route("test", 2, "10.0.0.2")
        self.assertFalse(Evidence(route, route, (None, None)).confirmed)
        with patch("windows_probe.current_route") as check_route, \
             patch("desktop_control.find_app") as find, \
             patch("desktop_control.probe_windows") as probe:
            with self.assertRaises(GuardDenied):
                probe_windows()
            with self.assertRaises(GuardDenied):
                DesktopGuard().launch("Orca")
        check_route.assert_not_called()
        find.assert_not_called()
        probe.assert_not_called()

    def test_amnezia_connect_requires_a_configured_server(self):
        with patch("desktop_control.powershell_json") as powershell:
            with self.assertRaises(GuardDenied):
                amnezia_ui("connect")
        powershell.assert_not_called()

    def test_override_is_saved_and_requires_the_known_exe_name(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            app, wrong = root / "Orca.exe", root / "other.exe"
            app.touch()
            wrong.touch()
            path = root / "settings.json"
            expected = Settings(app_paths={"Orca": str(app)})
            save_settings(expected, path)
            stored = load_settings(path)
            guard = DesktopGuard()
            guard.configured_paths = stored.app_paths
            self.assertEqual(guard.app_path("Orca"), app)
            self.assertFalse(valid_app_path("Orca", wrong))
            app.unlink()
            with patch("desktop_control.find_app") as lookup:
                self.assertIsNone(guard.app_path("Orca"))
            lookup.assert_not_called()

    def test_orca_can_be_found_in_a_standard_per_user_directory(self):
        import os

        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "Programs/orca/Orca.exe"
            path.parent.mkdir(parents=True)
            path.touch()
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root), "ProgramFiles": str(root / "global")}):
                self.assertEqual(find_app("Orca"), path)
