from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from settings import Settings, load_settings, save_settings
from tray import NativeTray, TrayStatus


class TrayStatusTests(unittest.TestCase):
    def test_ok_only_for_active_vpn_or_no_observed_vpn_and_closed_applications(self):
        scenarios = (
            (True, ("Codex CLI",), "ok"), (True, (), "ok"), (True, None, "ok"),
            (False, (), "ok"), (False, ("OpenCode CLI",), "warning"),
            (False, None, "unknown"), (None, (), "unknown"),
            (None, ("OpenCode CLI",), "unknown"), (None, None, "unknown"),
        )
        for vpn, running, expected in scenarios:
            with self.subTest(vpn=vpn, running=running):
                self.assertEqual(TrayStatus(vpn, running).level, expected)

    def test_same_state_does_not_repeat_the_notification(self):
        tray = NativeTray()
        tray.state = before = TrayStatus(True, ())
        tray.visible = True
        with patch.object(tray, "show") as show, patch.object(tray, "notify") as notify:
            tray.update(before)
            show.assert_not_called()
            notify.assert_not_called()
            changed = TrayStatus(False, ("OpenCode CLI",))
            tray.update(changed)
            show.assert_called_once_with(changed)
            notify.assert_called_once()

    def test_status_text_lists_custom_apps_and_unknown_snapshot(self):
        self.assertIn("Моя программа", TrayStatus(True, ("Моя программа",)).details)
        self.assertIn("неизвестен", TrayStatus(False, None).details)
        warning = TrayStatus(False, ("Моя программа",))
        self.assertEqual(warning.title, "Приложения без VPN")
        self.assertIn("Моя программа", warning.details)

    def test_older_settings_get_tray_by_default_and_explicit_opt_out_is_preserved(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"target_ip":"8.8.8.8","theme":"dark"}', encoding="utf-8")
            legacy = load_settings(path)
            self.assertTrue(legacy.minimize_to_tray)
            self.assertEqual(legacy.theme, "dark")
            saved = Settings("8.8.8.8", theme="dark", minimize_to_tray=False)
            save_settings(saved, path)
            self.assertEqual(load_settings(path), saved)
