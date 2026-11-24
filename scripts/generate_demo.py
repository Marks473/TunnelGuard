"""Render README screenshots from fixed demo data without reading the user's profile."""

import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

from PIL import Image
import win32gui
import win32ui

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from activity import ActivityTracker, Session, Usage, VpnIncident
from guard import APPLICATIONS
from news_feed import Article, NewsCache
from settings import Settings
from tray import TrayStatus, VpnAlert
from tunnelguard import TunnelGuardWindow
from windows_probe import Route


def capture(window, path):
    window.update()
    handle = int(window.frame(), 0)
    width, height = window.winfo_width(), window.winfo_height()
    print_window = ctypes.windll.user32.PrintWindow
    print_window.argtypes = (wintypes.HWND, wintypes.HDC, wintypes.UINT)
    print_window.restype = wintypes.BOOL
    screen = win32gui.GetDC(handle)
    source = win32ui.CreateDCFromHandle(screen)
    target = source.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source, width, height)
    target.SelectObject(bitmap)
    try:
        if not print_window(handle, target.GetSafeHdc(), 1):
            raise OSError(f"Failed to capture {path.name}")
        image = Image.frombuffer("RGB", (width, height), bitmap.GetBitmapBits(True), "raw", "BGRX", 0, 1)
        image.save(path)
    finally:
        target.DeleteDC()
        win32gui.DeleteObject(bitmap.GetHandle())
        win32gui.ReleaseDC(handle, screen)


def main():
    output = PROJECT / "docs" / "images"
    output.mkdir(parents=True, exist_ok=True)
    now = int(datetime(2026, 6, 12, 15, 40).timestamp())
    news = NewsCache(now, (
        Article("china", "A new DeepSeek model", "Demo Desk", now - 600, "Демо: новая модель DeepSeek"),
        Article("orca", "Orca worktrees guide", "Demo Desk", now - 900, "Демо: гайд по рабочим деревьям Orca"),
        Article("agents", "OpenCode improves CLI sessions", "Demo Desk", now - 1200, "Демо: улучшения сессий OpenCode CLI"),
        Article("labs", "A model release example", "Demo Desk", now - 1800, "Демо: анонс новой модели"),
        Article("models", "Model comparison example", "Demo Desk", now - 2100, "Демо: сравнение моделей"),
    ))
    process_sample = dict.fromkeys(APPLICATIONS, ())
    process_sample["OpenCode CLI"] = (4100,)
    usage = ActivityTracker(
        {"OpenCode CLI": Usage(8100, 8, now), "Orca": Usage(5120, 2, now - 3600)},
        (
            Session("OpenCode CLI", now - 1080, now, "guarded", seconds=1080,
                    checked_ip="203.0.113.42", pid=4100,
                    vpn_incidents=[VpnIncident(now - 480, now - 350, during_start=False)]),
            Session("Orca", now - 7200, now - 4000, "observed", status="closed",
                    ended_at=now - 3900, seconds=3300,
                    vpn_incidents=[VpnIncident(now - 7200, now - 7080, during_start=True)]),
        ),
    )
    usage.session_seconds["OpenCode CLI"] = 1080
    settings = Settings()
    # Documentation addresses are intentionally rejected by the real settings validator.
    object.__setattr__(settings, "target_ip", "203.0.113.42")
    object.__setattr__(settings, "vpn_server_ip", "198.51.100.42")
    demo_paths = {
        "Orca": Path(r"C:\Program Files\Orca\Orca.exe"),
        "Claude": Path(r"C:\Apps\ClaudeCode\claude.exe"),
        "Codex CLI": Path(r"C:\Apps\Codex\codex.exe"),
        "Dolphin Anty": Path(r"C:\Program Files\Dolphin Anty\Dolphin Anty.exe"),
        "Visual Studio Code": Path(r"C:\Program Files\Microsoft VS Code\Code.exe"),
        "OpenCode CLI": Path(r"C:\Apps\OpenCode\opencode.exe"),
    }
    with patch("tunnelguard.load_catalog", return_value=()), \
         patch("tunnelguard.load_news", return_value=news), \
         patch("tunnelguard.load_activity", return_value=usage), \
         patch("tunnelguard.load_settings", return_value=settings), \
         patch("tunnelguard.autostart_enabled", return_value=False), \
         patch("tunnelguard.find_app", side_effect=demo_paths.get), \
         patch("desktop_control.find_app", side_effect=demo_paths.get), \
         patch("desktop_control.active_windows_apps", return_value=process_sample), \
         patch("tunnelguard.fetch_news", side_effect=AssertionError("Demo must remain offline")):
        root = tk.Tk()
        try:
            view = TunnelGuardWindow(root, monitor=False)
            root.geometry("1180x1025+36+25")
            view.route = Route("demo", 0, "192.0.2.10")
            view.route_known = True
            view.ip_confirmed = True
            view.render_network()
            capture(root, output / "library.png")
            root.geometry("1180x695+36+25")
            view.select_filter("news")
            capture(root, output / "news.png")
            view.select_filter("history")
            capture(root, output / "history.png")
            view.open_settings()
            settings_dialog = view.settings_window
            view.open_application_paths(settings_dialog)
            path_dialog = next(child for child in settings_dialog.winfo_children() if isinstance(child, tk.Toplevel))
            capture(path_dialog, output / "app-paths.png")
            alert = VpnAlert(root, lambda: None)
            alert.update(TrayStatus(False, ("Orca", "OpenCode CLI", "Visual Studio Code")))
            capture(alert.window, output / "vpn-alert.png")
        finally:
            root.destroy()


if __name__ == "__main__":
    main()
