from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app_catalog import CatalogError, CustomApp, load_catalog, save_catalog
from desktop_control import DesktopGuard, _AMNEZIA_UI, amnezia_ui, find_app
from guard import Evidence, GuardDenied
from windows_probe import APPLICATION_BY_EXE, Route, active_windows_apps


class CatalogTests(unittest.TestCase):
    def test_catalog_round_trips_and_keeps_unavailable_programs(self):
        with TemporaryDirectory() as folder:
            directory = Path(folder)
            path = directory / "applications.json"
            apps = (CustomApp("Мой терминал", directory / "my-cli.exe", console=True),)
            self.assertEqual(load_catalog(APPLICATION_BY_EXE, path), ())
            save_catalog(apps, path)
            self.assertEqual(load_catalog(APPLICATION_BY_EXE, path), apps)

    def test_existing_process_names_cannot_be_reassigned(self):
        app = CustomApp("Редактор", Path.cwd() / "CoDe.ExE")
        with patch("desktop_control.save_catalog") as save:
            with self.assertRaises(CatalogError):
                DesktopGuard().add_app(app)
            save.assert_not_called()

    def test_process_snapshot_and_vpn_disconnect_include_custom_and_opencode(self):
        app = CustomApp("Локальный инструмент", Path.cwd() / "custom-tool.exe")
        guard = DesktopGuard((app,))
        with patch("windows_probe.windows_processes", return_value=[("CUSTOM-TOOL.EXE", 42), ("OpenCode.exe", 13)]), \
             patch("desktop_control.amnezia_ui") as control:
            self.assertEqual(guard.running_apps()[app.name], (42,))
            self.assertEqual(active_windows_apps()["OpenCode CLI"], (13,))
            with self.assertRaises(GuardDenied):
                guard.disconnect()
            control.assert_not_called()
        with patch("windows_probe.windows_processes", return_value=[]), \
             patch("desktop_control.amnezia_ui", return_value={"changed": True}) as control:
            self.assertTrue(guard.disconnect())
            control.assert_called_once_with("disconnect", custom_apps=(app,))

    def test_powershell_recheck_matches_builtin_and_custom_process_names(self):
        app = CustomApp("Терминал", Path.cwd() / "tool ’ testing.exe")
        functions = _AMNEZIA_UI.split("try {", 1)[0]
        fake_processes = r"""
function Get-Process {
    [PSCustomObject]@{ ProcessName = 'OpenCode' }
    [PSCustomObject]@{ ProcessName = ('tool ' + [char]0x2019 + ' testing') }
    [PSCustomObject]@{ ProcessName = 'unrelated' }
}
@{ active = @(Get-ActiveNames) } | ConvertTo-Json -Compress
"""
        with patch("desktop_control._AMNEZIA_UI", functions + fake_processes):
            result = amnezia_ui("disconnect", custom_apps=(app,))
        self.assertEqual(result["active"], ["OpenCode", "tool ’ testing"])

    def test_invalid_catalog_stops_disconnect_before_talking_to_amnezia(self):
        with TemporaryDirectory() as folder, patch("desktop_control.amnezia_ui") as control:
            path = Path(folder) / "applications.json"
            path.write_text('{"invalid": 1}', encoding="utf-8")
            with self.assertRaises(CatalogError):
                load_catalog(APPLICATION_BY_EXE, path)
            with self.assertRaises(GuardDenied):
                DesktopGuard(catalog_error="Invalid catalog").disconnect()
            control.assert_not_called()

    def test_opencode_npm_shim_resolves_direct_executable(self):
        with TemporaryDirectory() as folder:
            npm = Path(folder)
            executable = npm / "node_modules/opencode-ai/bin/opencode.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch("desktop_control.shutil.which", side_effect=lambda name: str(npm / "opencode.cmd")
                       if name == "opencode.cmd" else None):
                self.assertEqual(find_app("OpenCode CLI"), executable)

    def test_custom_console_launch_stops_on_wrong_ip_or_changed_route(self):
        import subprocess

        with TemporaryDirectory() as folder:
            app = CustomApp("Терминал", Path(folder) / "my-cli.exe", console=True)
            app.path.touch()
            route = Route("test", 2, "10.0.0.2")
            target = "203.0.113.42"
            with patch("windows_probe.windows_processes", return_value=[]), \
                 patch("desktop_control.probe_windows") as probe, \
                 patch("desktop_control.current_route", return_value=None) as current, \
                 patch("desktop_control.subprocess.Popen") as start:
                guard = DesktopGuard((app,))
                probe.return_value = Evidence(route, route, (target, "192.0.2.1"), target), []
                with self.assertRaises(GuardDenied):
                    guard.launch(app.name, target)
                probe.return_value = Evidence(route, route, (target, target), target), []
                with self.assertRaises(GuardDenied):
                    guard.launch(app.name, target)
                start.assert_not_called()
                current.return_value = route
                guard.launch(app.name, target)
                start.assert_called_once_with([str(app.path)], cwd=Path.home(),
                                              creationflags=subprocess.CREATE_NEW_CONSOLE, shell=False)
