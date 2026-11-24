from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, SimpleQueue
from tempfile import TemporaryDirectory
from threading import Thread

from PIL import ImageDraw
import pywintypes
import win32api
import win32con as con
import win32gui as gui

from launcher_art import brand_icon


WINDOW_CLASS = "TunnelGuard.TrayWindow.v1"
SHOW_MESSAGE = "TunnelGuard.TrayWindow.Show.v1"
TRAY_CALLBACK = con.WM_APP + 1
TRAY_COMMAND = con.WM_APP + 2
OPEN_ITEM, STATUS_ITEM, EXIT_ITEM = 101, 102, 103
STATUS_COLORS = {"ok": "#36d399", "warning": "#fb9a54", "unknown": "#9e95b1"}


@dataclass(frozen=True)
class TrayStatus:
    vpn: bool | None
    running: tuple[str, ...] | None

    @property
    def level(self):
        if self.vpn is True or (self.vpn is False and self.running == ()):
            return "ok"
        if self.vpn is False and self.running:
            return "warning"
        return "unknown"

    @property
    def title(self):
        return {"ok": "ОК", "warning": "Внимание", "unknown": "Нет данных"}[self.level]

    @property
    def vpn_text(self):
        return {True: "VPN активен", False: "VPN не подтверждён", None: "Статус VPN неизвестен"}[self.vpn]

    @property
    def programs_text(self):
        if self.running is None:
            return "Статус приложений неизвестен"
        if self.running:
            return "Работают: " + ", ".join(self.running)
        return "Приложения закрыты"

    @property
    def details(self):
        return f"{self.vpn_text}\n{self.programs_text}"


def request_open():
    try:
        window = gui.FindWindow(WINDOW_CLASS, None)
        if window:
            gui.PostMessage(window, gui.RegisterWindowMessage(SHOW_MESSAGE), 0, 0)
            return True
    except pywintypes.error:
        pass
    return False


class TrayIcon:
    """Keep the Win32 message loop separate from the Tk event loop."""

    def __init__(self, root, on_open, on_exit):
        self.root = root
        self.actions = {"open": on_open, "exit": on_exit}
        self.closed = False
        self.native = NativeTray()
        self.thread = Thread(target=self.native.run, daemon=True)
        self.thread.start()
        self.native.ready.result(timeout=4)
        self.poll_job = self.root.after(75, self.poll)

    def poll(self):
        self.poll_job = None
        while not self.closed:
            try:
                action = self.native.events.get_nowait()
            except Empty:
                break
            self.actions[action]()
        if not self.closed:
            self.poll_job = self.root.after(75, self.poll)

    def send(self, method, *args, wait=False):
        result = Future() if wait else None
        self.native.commands.put((method, args, result))
        gui.PostMessage(self.native.hwnd, TRAY_COMMAND, 0, 0)
        if result is not None:
            result.result(timeout=4)

    def show(self, status):
        self.send(self.native.show, status, wait=True)

    def update(self, status):
        try:
            self.send(self.native.update, status)
        except pywintypes.error:
            self.actions["open"]()

    def notify(self):
        try:
            self.send(self.native.notify)
        except pywintypes.error:
            pass

    def hide(self):
        try:
            self.send(self.native.hide)
        except pywintypes.error:
            pass

    def close(self):
        self.closed = True
        if self.poll_job is not None:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None
        if self.thread.is_alive():
            try:
                self.send(self.native.quit, wait=True)
            except (OSError, pywintypes.error):
                pass
            self.thread.join(timeout=1)


class NativeTray:
    def __init__(self):
        self.ready = Future()
        self.commands = SimpleQueue()
        self.events = SimpleQueue()
        self.state = TrayStatus(None, None)
        self.visible = False
        self.hwnd = None
        self.atom = None
        self.icons = {}

    def run(self):
        try:
            self.instance = win32api.GetModuleHandle(None)
            self.taskbar_created = gui.RegisterWindowMessage("TaskbarCreated")
            self.open_message = gui.RegisterWindowMessage(SHOW_MESSAGE)
            self.load_icons()
            definition = gui.WNDCLASS()
            definition.hInstance = self.instance
            definition.lpszClassName = WINDOW_CLASS
            definition.lpfnWndProc = self.window_proc
            self.atom = gui.RegisterClass(definition)
            self.hwnd = gui.CreateWindowEx(con.WS_EX_TOOLWINDOW, self.atom, "TunnelGuard tray",
                                           con.WS_POPUP, 0, 0, 0, 0, 0, 0, self.instance, None)
            self.ready.set_result(None)
            gui.PumpMessages()
        except (OSError, pywintypes.error) as error:
            if not self.ready.done():
                self.ready.set_exception(error)
            else:
                self.events.put("open")
        finally:
            self.hide()
            if self.hwnd:
                gui.DestroyWindow(self.hwnd)
            if self.atom:
                gui.UnregisterClass(self.atom, self.instance)
            for handle in self.icons.values():
                gui.DestroyIcon(handle)

    def load_icons(self):
        with TemporaryDirectory(prefix="tunnelguard-tray-") as folder:
            for level, color in STATUS_COLORS.items():
                image = brand_icon(64)
                draw = ImageDraw.Draw(image)
                draw.ellipse((41, 41, 63, 63), fill="#221b36")
                draw.ellipse((44, 44, 60, 60), fill=color)
                path = Path(folder) / f"{level}.ico"
                image.save(path, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (64, 64)])
                self.icons[level] = gui.LoadImage(0, str(path), con.IMAGE_ICON, 0, 0,
                                                 con.LR_LOADFROMFILE | con.LR_DEFAULTSIZE)

    def icon_data(self, flags):
        return (self.hwnd, 0, flags, TRAY_CALLBACK, self.icons[self.state.level],
                f"TunnelGuard · {self.state.title}\n{self.state.details}"[:120])

    def show(self, status):
        self.state = status
        flags = gui.NIF_ICON | gui.NIF_MESSAGE | gui.NIF_TIP
        gui.Shell_NotifyIcon(gui.NIM_MODIFY if self.visible else gui.NIM_ADD, self.icon_data(flags))
        self.visible = True

    def hide(self):
        if self.visible:
            try:
                gui.Shell_NotifyIcon(gui.NIM_DELETE, (self.hwnd, 0))
            except pywintypes.error:
                pass
            self.visible = False

    def update(self, status):
        if self.visible and status != self.state:
            self.show(status)
            self.notify()

    def notify(self):
        if not self.visible:
            return
        flags = gui.NIIF_WARNING if self.state.level == "warning" else gui.NIIF_INFO
        data = self.icon_data(gui.NIF_INFO) + (self.state.details[:240], 7000,
                                               f"TunnelGuard · {self.state.title}", flags)
        try:
            gui.Shell_NotifyIcon(gui.NIM_MODIFY, data)
        except pywintypes.error:
            # Explorer can discard notifications independently of the icon.
            pass

    def show_menu(self):
        menu = gui.CreatePopupMenu()
        try:
            gui.AppendMenu(menu, con.MF_STRING | con.MF_GRAYED, 0, f"{self.state.title} · {self.state.vpn_text}")
            running = self.state.running or ()
            listing = f"Запущенные приложения ({len(running)})" if running else self.state.programs_text
            gui.AppendMenu(menu, con.MF_STRING | con.MF_GRAYED, 0, listing)
            for name in running[:12]:
                gui.AppendMenu(menu, con.MF_STRING | con.MF_GRAYED, 0, "   " + name.replace("&", "&&"))
            if len(running) > 12:
                gui.AppendMenu(menu, con.MF_STRING | con.MF_GRAYED, 0, f"   Ещё {len(running) - 12}")
            gui.AppendMenu(menu, con.MF_SEPARATOR, 0, "")
            gui.AppendMenu(menu, con.MF_STRING, OPEN_ITEM, "Открыть TunnelGuard")
            gui.AppendMenu(menu, con.MF_STRING, STATUS_ITEM, "Показать состояние")
            gui.AppendMenu(menu, con.MF_STRING, EXIT_ITEM, "Выйти")
            x, y = gui.GetCursorPos()
            try:
                gui.SetForegroundWindow(self.hwnd)
            except pywintypes.error:
                pass
            gui.TrackPopupMenu(menu, con.TPM_LEFTALIGN | con.TPM_RIGHTBUTTON, x, y, 0, self.hwnd, None)
            gui.PostMessage(self.hwnd, con.WM_NULL, 0, 0)
        finally:
            gui.DestroyMenu(menu)

    def quit(self):
        gui.PostQuitMessage(0)

    def handle_command(self):
        try:
            method, args, result = self.commands.get_nowait()
        except Empty:
            return
        try:
            method(*args)
        except (OSError, pywintypes.error) as error:
            if result is None:
                self.events.put("open")
            else:
                result.set_exception(error)
        else:
            if result is not None:
                result.set_result(None)

    def window_proc(self, hwnd, message, wparam, lparam):
        if message == TRAY_COMMAND:
            self.handle_command()
            return 0
        if message == self.taskbar_created and self.visible:
            self.visible = False
            try:
                self.show(self.state)
            except pywintypes.error:
                self.events.put("open")
            return 0
        if message == self.open_message:
            self.events.put("open")
            return 0
        if message == TRAY_CALLBACK:
            if lparam in (con.WM_LBUTTONUP, con.WM_LBUTTONDBLCLK):
                self.events.put("open")
            elif lparam in (con.WM_RBUTTONUP, con.WM_CONTEXTMENU):
                self.show_menu()
            return 0
        if message == con.WM_COMMAND:
            selected = wparam & 0xFFFF
            if selected == STATUS_ITEM:
                self.notify()
            elif selected in (OPEN_ITEM, EXIT_ITEM):
                self.events.put("open" if selected == OPEN_ITEM else "exit")
            return 0
        return gui.DefWindowProc(hwnd, message, wparam, lparam)
