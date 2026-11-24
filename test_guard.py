import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch

from desktop_control import DesktopGuard, find_app
from guard import APPLICATIONS, Evidence, Guard, GuardDenied, LabBackend, parse_ip
from settings import Settings, SettingsError, load_settings, save_settings
from windows_probe import Route, active_windows_apps, probe_windows


REQUIRED_IP = "203.0.113.42"


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.backend = LabBackend()
        self.guard = Guard(self.backend)

    def test_each_application_blocks_disconnect_in_background(self):
        for name in APPLICATIONS:
            with self.subTest(application=name):
                self.guard.connect()
                self.guard.launch(name)
                with self.assertRaises(GuardDenied):
                    self.guard.disconnect()
                self.backend.close_window(name)
                with self.assertRaises(GuardDenied):
                    self.guard.disconnect()
                self.backend.finish(name)
                self.assertTrue(self.backend.connected)
                self.guard.disconnect()
                self.assertFalse(self.backend.connected)

    def test_launch_requires_tunnel_and_both_ip_answers(self):
        with self.assertRaises(GuardDenied):
            self.guard.launch("Orca")
        self.guard.connect()
        for addresses in ((REQUIRED_IP, None), ("192.0.2.1", REQUIRED_IP), ("192.0.2.1",) * 2):
            with self.subTest(addresses=addresses):
                self.backend.addresses = addresses
                with self.assertRaises(GuardDenied):
                    self.guard.launch("Orca")
                self.assertFalse(self.backend.access_open)
                self.assertEqual(self.backend.active(), ())

    def test_route_changes_between_check_and_access(self):
        self.guard.connect()
        real_verify = self.backend.verify

        def change_route():
            evidence = real_verify()
            self.backend.generation += 1
            return evidence

        with patch.object(self.backend, "verify", side_effect=change_route):
            with self.assertRaises(GuardDenied):
                self.guard.launch("Orca")
        self.assertFalse(self.backend.access_open)
        self.assertEqual(self.backend.active(), ())

    def test_tunnel_loss_and_revalidation(self):
        self.guard.connect()
        self.guard.launch("Orca")
        self.backend.disconnect()
        self.assertFalse(self.backend.access_open)
        self.assertEqual(self.backend.active(), ("Orca",))
        self.guard.connect()
        self.assertFalse(self.backend.access_open)
        self.guard.recheck()
        self.assertTrue(self.backend.access_open)
        self.backend.addresses = (REQUIRED_IP, None)
        with self.assertRaises(GuardDenied):
            self.guard.recheck()
        self.assertFalse(self.backend.access_open)

    def test_unknown_processes_block_disconnect_and_launch(self):
        self.guard.connect()
        with patch.object(self.backend, "active", return_value=None):
            with self.assertRaises(GuardDenied):
                self.guard.disconnect()
            with self.assertRaises(GuardDenied):
                self.guard.launch("Orca")
        self.assertTrue(self.backend.connected)
        self.assertFalse(self.backend.access_open)

    def test_failed_launch_revokes_access(self):
        self.guard.connect()
        with patch.object(self.backend, "launch", side_effect=OSError("launch error")):
            with self.assertRaises(OSError):
                self.guard.launch("Orca")
        self.assertFalse(self.backend.access_open)

    def test_launch_serializes_with_disconnect(self):
        self.guard.connect()
        verifying, release = Event(), Event()
        errors = []
        verify = self.backend.verify

        def delayed_verification():
            verifying.set()
            if not release.wait(3):
                raise RuntimeError("verification timed out")
            return verify()

        def call(action, *args):
            try:
                action(*args)
            except Exception as error:
                errors.append(error)

        launch = Thread(target=call, args=(self.guard.launch, "Orca"), daemon=True)
        disconnect = Thread(target=call, args=(self.guard.disconnect,), daemon=True)
        with patch.object(self.backend, "verify", side_effect=delayed_verification):
            launch.start()
            try:
                self.assertTrue(verifying.wait(3))
                disconnect.start()
            finally:
                release.set()
            launch.join(3)
            disconnect.join(3)
        self.assertFalse(launch.is_alive() or disconnect.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], GuardDenied)
        self.assertTrue(self.backend.connected)
        self.assertEqual(self.backend.active(), ("Orca",))


class ProbeTests(unittest.TestCase):
    def test_running_natively_and_in_background_are_reported_as_real_processes(self):
        processes = [("CoDeX.EXE", 42), ("codex-code-mode-host.exe", 31),
                     ("Dolphin Anty.exe", 56), ("fake-codex.exe", 60), ("Code.exe", 73), ("Code.exe", 66)]
        with patch("windows_probe.windows_processes", return_value=processes):
            self.assertEqual(active_windows_apps(), {
                "Orca": (), "Claude": (), "Codex CLI": (31, 42), "Dolphin Anty": (56,),
                "Visual Studio Code": (66, 73), "OpenCode CLI": (),
            })

    def test_parse_ipv4(self):
        self.assertEqual(parse_ip(b"203.0.113.42\n"), REQUIRED_IP)
        for invalid in (b"::ffff:203.0.113.42", b"203.0.113.042", b"203.0.113.42 extra", b"\xff"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_ip(invalid)

    def test_route_change_invalidates_two_good_answers(self):
        initial = Route("test", 2, "10.0.0.2")
        after = Route("test", 3, "10.0.0.2")
        with patch("windows_probe.current_route", side_effect=(initial, after)), \
             patch("windows_probe.query_ip", return_value=REQUIRED_IP) as query:
            evidence, errors = probe_windows(REQUIRED_IP)
        self.assertEqual(query.call_count, 2)
        self.assertEqual(errors, [])
        self.assertFalse(evidence.confirmed)

    def test_one_probe_error_is_not_a_confirmation(self):
        route = Route("test", 2, "10.0.0.2")
        with patch("windows_probe.current_route", return_value=route), \
             patch("windows_probe.query_ip", side_effect=(TimeoutError(), REQUIRED_IP)):
            evidence, errors = probe_windows(REQUIRED_IP)
        self.assertEqual(evidence, Evidence(route, route, (None, REQUIRED_IP), REQUIRED_IP))
        self.assertEqual(len(errors), 1)
        self.assertFalse(evidence.confirmed)

    def test_inactive_tunnel_prevents_outbound_probes(self):
        with patch("windows_probe.current_route", return_value=None), patch("windows_probe.query_ip") as query:
            with self.assertRaises(GuardDenied):
                probe_windows(REQUIRED_IP)
        query.assert_not_called()


class DesktopGuardTests(unittest.TestCase):
    def test_running_app_stops_disconnect_before_talking_to_amnezia(self):
        for app in ("Codex CLI", "Visual Studio Code"):
            with self.subTest(app=app), \
                 patch("desktop_control.active_windows_apps", return_value={app: (31,)}), \
                 patch("desktop_control.amnezia_ui") as control:
                with self.assertRaises(GuardDenied):
                    DesktopGuard().disconnect()
                control.assert_not_called()

    def test_disconnected_action_uses_amnezia_only_when_no_apps_run(self):
        with patch("desktop_control.active_windows_apps", return_value={"Codex CLI": ()}), \
             patch("desktop_control.amnezia_ui", return_value={"changed": True}) as control:
            self.assertTrue(DesktopGuard().disconnect())
            control.assert_called_once_with("disconnect")

    def test_connect_when_running_does_not_toggle_vpn(self):
        with patch("desktop_control.current_route", return_value=object()), \
             patch("desktop_control.amnezia_ui") as control:
            self.assertFalse(DesktopGuard().connect())
            control.assert_not_called()

    def test_connect_uses_server_address_selected_in_settings(self):
        with patch("desktop_control.current_route", return_value=None), \
             patch("desktop_control.amnezia_ui", return_value={"changed": True}) as control:
            self.assertTrue(DesktopGuard().connect("10.5.4.3"))
            control.assert_called_once_with("connect", server_ip="10.5.4.3")

    def test_vscode_launch_stops_on_wrong_ipv4_and_accepts_split_tunneling(self):
        route = Route("test", 2, "10.0.0.2")
        app = "Visual Studio Code"
        path = Path("VS Code") / "Code.exe"
        with patch("desktop_control.find_app", return_value=path), \
             patch("desktop_control.active_windows_apps", return_value={app: ()}), \
             patch("desktop_control.amnezia_ui", return_value={"split": "on"}) as amnezia_ui, \
             patch("desktop_control.current_route", return_value=route), \
             patch("desktop_control.probe_windows") as probe, \
             patch("desktop_control.subprocess.Popen") as launch:
            probe.return_value = (Evidence(route, route, (REQUIRED_IP, "192.0.2.1"), REQUIRED_IP), [])
            with self.assertRaises(GuardDenied):
                DesktopGuard().launch(app, REQUIRED_IP)
            launch.assert_not_called()
            probe.return_value = (Evidence(route, route, (REQUIRED_IP,) * 2, REQUIRED_IP), [])
            DesktopGuard().launch(app, REQUIRED_IP)
            launch.assert_called_once_with([str(path)], cwd=path.parent, creationflags=0, shell=False)
            amnezia_ui.assert_not_called()

    def test_vscode_location_from_code_cmd_in_path(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            app = base / "VS Code"
            (app / "bin").mkdir(parents=True)
            executable = app / "Code.exe"
            executable.touch()
            launcher = app / "bin" / "code.cmd"
            launcher.touch()
            with patch.dict(os.environ, {"LOCALAPPDATA": str(base / "Local"), "ProgramFiles": str(base / "Programs")}), \
                 patch("desktop_control.shutil.which", side_effect=lambda name: str(launcher) if name == "code.cmd" else None):
                self.assertEqual(find_app("Visual Studio Code"), executable)

    def test_launch_accepts_new_target_and_rejects_old_target(self):
        target = "8.8.4.4"
        route = Route("test", 2, "10.0.0.2")
        path = Path("codex.exe")
        with patch("desktop_control.find_app", return_value=path), \
             patch("desktop_control.active_windows_apps", return_value={"Codex CLI": ()}), \
             patch("desktop_control.amnezia_ui", return_value={"split": "off"}), \
             patch("desktop_control.current_route", return_value=route), \
             patch("desktop_control.probe_windows") as probe, \
             patch("desktop_control.subprocess.Popen") as launch:
            probe.return_value = (Evidence(route, route, (REQUIRED_IP,) * 2, target), [])
            with self.assertRaises(GuardDenied):
                DesktopGuard().launch("Codex CLI", target)
            launch.assert_not_called()
            probe.return_value = (Evidence(route, route, (target,) * 2, target), [])
            launch.return_value.pid = 123
            self.assertEqual(DesktopGuard().launch("Codex CLI", target), 123)
            probe.assert_called_with(target)
            launch.assert_called_once()


class SettingsTests(unittest.TestCase):
    def test_light_theme_defaults_for_existing_profiles_and_dark_theme_persists(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"target_ip":"8.8.8.8","vpn_server_ip":"10.5.4.3"}', encoding="utf-8")
            self.assertEqual(load_settings(path), Settings("8.8.8.8", "10.5.4.3", "light"))
            dark = Settings("8.8.8.8", "10.5.4.3", "dark")
            save_settings(dark, path)
            self.assertEqual(load_settings(path), dark)

    def test_missing_settings_and_save_reload(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "settings.json"
            self.assertEqual(load_settings(path), Settings())
            initial = Settings(" 8.8.8.8 ", "10.5.4.3")
            save_settings(initial, path)
            self.assertEqual(load_settings(path), Settings("8.8.8.8", "10.5.4.3"))
            save_settings(Settings(), path)
            self.assertEqual(load_settings(path), Settings())
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_invalid_settings_do_not_silently_use_default(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            for data in ("{", "{}", '{"target_ip": "::1"}', '{"target_ip": 8888}'):
                with self.subTest(data=data), self.assertRaises(SettingsError):
                    path.write_text(data, encoding="utf-8")
                    load_settings(path)

    def test_target_requires_public_ipv4(self):
        for value in ("10.0.0.1", "8.8.4.4:443", "8.8.4.4/32", "224.0.0.1"):
            with self.subTest(value=value), self.assertRaises(SettingsError):
                Settings(value)


if __name__ == "__main__":
    unittest.main()
