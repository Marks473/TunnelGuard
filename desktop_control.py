from base64 import b64encode
import json
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import shutil
import subprocess
import sys
from threading import RLock

from app_catalog import CatalogError, save_catalog, validate_catalog
from guard import APPLICATIONS, GuardDenied
from settings import DEFAULT_TARGET_IP, DEFAULT_VPN_SERVER_IP, normalize_ipv4
from windows_probe import (
    APPLICATION_BY_EXE, active_windows_apps, current_route, powershell_json, probe_windows,
)


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "TunnelGuard"

_AMNEZIA_UI = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$exe = Join-Path $env:ProgramFiles 'AmneziaVPN\AmneziaVPN.exe'
function Find-Window {
    $owners = @(Get-Process -Name AmneziaVPN -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -ieq $exe -and $_.MainWindowHandle -ne 0 -and $_.SessionId -eq (Get-Process -Id $PID).SessionId
    })
    if ($owners.Count -eq 1) {
        [System.Windows.Automation.AutomationElement]::FromHandle($owners[0].MainWindowHandle)
    }
}
function Find-MainControls($window) {
    $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
}
function Get-ActiveNames {
    @(Get-Process | Where-Object { $_.ProcessName -iin $targets } | Select-Object -ExpandProperty ProcessName)
}
try {
    if ($operation -eq 'disconnect' -and @(Get-ActiveNames).Count -gt 0) {
        throw 'Закрой защищённые приложения перед отключением VPN.'
    }
    Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes
    $window = Find-Window
    if (-not $window -and $operation -eq 'connect' -and (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Start-Process -FilePath $exe
        for ($i = 0; $i -lt 20 -and -not $window; $i++) {
            Start-Sleep -Milliseconds 250
            $window = Find-Window
        }
    }
    if (-not $window) { throw 'Открой главное окно AmneziaVPN.' }
    $elements = @(Find-MainControls $window)
    $buttons = @($elements | Where-Object {
        $_.Current.ClassName -cmatch '^ConnectButton_' -and -not $_.Current.IsOffscreen
    })
    if ($buttons.Count -ne 1) { throw 'Перейди на главную страницу AmneziaVPN.' }
    $button = $buttons[0]
    $caption = $button.Current.Name
    $split = 'unknown'
    foreach ($element in $elements) {
        if ($element.Current.IsOffscreen) { continue }
        if ($element.Current.Name -in @('Раздельное туннелирование включено','Split tunneling enabled')) {
            $split = 'on'
            break
        }
        if ($element.Current.Name -in @('Раздельное туннелирование выключено','Раздельное туннелирование отключено','Split tunneling disabled')) {
            $split = 'off'
        }
    }
    if ($operation -eq 'inspect') {
        @{ split = $split; caption = $caption } | ConvertTo-Json -Compress
        exit
    }
    $connected = @('Подключено','Connected','Отключиться','Disconnect')
    $disconnected = @('Подключиться','Подключить','Не подключено','Отключено','Connect','Disconnected')
    $service = Get-Service -Name 'AmneziaWGTunnel$AmneziaVPN' -ErrorAction SilentlyContinue
    if ($operation -eq 'connect') {
        if ($caption -in $connected -and $service.Status -eq 'Running') { '{"changed":false}'; exit }
        if ($caption -notin $disconnected -or ($service -and $service.Status -ne 'Stopped')) {
            throw 'Подключение ещё меняет состояние. Повтори проверку.'
        }
        $profilePattern = '(?<![\d.])' + [regex]::Escape($serverIp) + '(?![\d.])'
        $profile = @($elements | Where-Object {
            -not $_.Current.IsOffscreen -and $_.Current.Name -match $profilePattern -and
            $_.Current.Name -match '^AmneziaWG\b'
        })
        if ($profile.Count -eq 0) { throw "Выбери профиль AmneziaWG с адресом $serverIp в AmneziaVPN." }
    } else {
        if ($caption -in $disconnected -and (-not $service -or $service.Status -eq 'Stopped')) {
            '{"changed":false}'; exit
        }
        if ($caption -notin $connected -or $service.Status -ne 'Running') {
            throw 'Не удалось подтвердить, что открыт подключённый профиль AmneziaWG.'
        }
    }
    $invoke = $null
    if (-not $button.Current.IsEnabled -or
        -not $button.TryGetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern, [ref]$invoke) -or
        $button.Current.Name -cne $caption) { throw 'Кнопка AmneziaVPN изменила состояние. Повтори проверку.' }
    if ($operation -eq 'disconnect' -and @(Get-ActiveNames).Count -gt 0) {
        throw 'Защищённое приложение запустилось. Отключение отменено.'
    }
    if ($button.Current.Name -cne $caption) { throw 'Состояние AmneziaVPN изменилось. Действие отменено.' }
    $invoke.Invoke()
    '{"changed":true}'
} catch {
    @{ error = $_.Exception.Message } | ConvertTo-Json -Compress
}
"""


def amnezia_ui(operation, *, server_ip=DEFAULT_VPN_SERVER_IP, custom_apps=()):
    if operation not in {"inspect", "connect", "disconnect"}:
        raise ValueError("Unknown Amnezia operation")
    if operation == "connect" and server_ip is None:
        raise GuardDenied("Укажи адрес сервера AmneziaWG в настройках.")
    server_ip = normalize_ipv4(server_ip) if operation == "connect" else ""
    executables = (*APPLICATION_BY_EXE, *(app.path.name for app in custom_apps))
    names = [Path(name).stem for name in executables]
    encoded = b64encode(json.dumps(names).encode("utf-8")).decode("ascii")
    parameters = (
        f"$operation = '{operation}'\n$serverIp = '{server_ip}'\n"
        f"$targets = ConvertFrom-Json -InputObject "
        f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded}')))\n"
    )
    result = powershell_json(parameters + _AMNEZIA_UI, timeout=12)
    if "error" in result:
        raise GuardDenied(result["error"])
    return result


def executable_names(app):
    return tuple(exe for exe, name in APPLICATION_BY_EXE.items()
                 if name == app and exe != "codex-code-mode-host.exe")


def valid_app_path(app, path):
    return (path.is_absolute() and not path.drive.startswith(chr(92) * 2)
            and path.name.casefold() in executable_names(app) and path.is_file())


def find_app(app):
    expected = executable_names(app)
    if not expected:
        return None
    local = Path(os.environ["LOCALAPPDATA"])
    program_roots = [local / "Programs", Path(os.environ["ProgramFiles"])]
    if os.environ.get("ProgramFiles(x86)"):
        program_roots.append(Path(os.environ["ProgramFiles(x86)"]))
    folders = {
        "Orca": ("orca",),
        "Claude": ("Claude",),
        "Codex CLI": ("OpenAI/Codex/bin", "Codex"),
        "Dolphin Anty": ("Dolphin Anty", "dolphin-anty"),
        "Visual Studio Code": ("Microsoft VS Code",),
        "OpenCode CLI": ("OpenCode",),
    }
    special = {
        "Claude": (Path.home() / ".local/bin/claude.exe",),
    }
    for path in (*special.get(app, ()), *(root / folder / exe for root in program_roots
                                         for folder in folders[app] for exe in expected)):
        if valid_app_path(app, path):
            return path
    for exe in expected:
        direct = shutil.which(exe)
        if direct and valid_app_path(app, Path(direct)):
            return Path(direct)

    if app == "Visual Studio Code":
        shim = shutil.which("code.cmd")
        if shim:
            parent = Path(shim).parent
            executable = parent.parent / "Code.exe"
            if parent.name.casefold() == "bin" and valid_app_path(app, executable):
                return executable
    elif app in {"OpenCode CLI", "Claude", "Codex CLI"}:
        shim = shutil.which({"OpenCode CLI": "opencode.cmd", "Claude": "claude.cmd", "Codex CLI": "codex.cmd"}[app])
        npm_paths = [Path(os.environ["APPDATA"]) / "npm"]
        if shim:
            npm_paths.insert(0, Path(shim).parent)
        relative_paths = {
            "OpenCode CLI": ("opencode-ai/bin/opencode.exe",),
            "Claude": ("@anthropic-ai/claude-code/bin/claude.exe", "@anthropic-ai/claude-code/claude.exe",
                       "@anthropic-ai/claude-code-win32-x64/claude.exe",
                       "@anthropic-ai/claude-code-win32-arm64/claude.exe"),
            "Codex CLI": ("@openai/codex/vendor/*/codex/codex.exe",
                          "@openai/codex-win32*/vendor/*/codex/codex.exe",
                          "@openai/codex/node_modules/@openai/codex-win32*/vendor/*/codex/codex.exe"),
        }
        for npm in npm_paths:
            for pattern in relative_paths[app]:
                for candidate in sorted((npm / "node_modules").glob(pattern)):
                    if valid_app_path(app, candidate):
                        return candidate
    return None


def set_autostart(enabled):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                command = subprocess.list2cmdline([sys.executable, "--startup"])
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                script = Path(__file__).with_name("tunnelguard.py")
                command = subprocess.list2cmdline([str(pythonw), str(script), "--startup"])
            # Quote the executable even when the current path contains no spaces.
            if not command.startswith('"'):
                exe, arguments = command.split(" ", 1)
                command = f'"{exe}" {arguments}'
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def autostart_enabled():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return bool(winreg.QueryValueEx(key, RUN_NAME)[0])
    except OSError:
        return False


def reserve_desktop_instance():
    native = ctypes.WinDLL("kernel32", use_last_error=True)
    native.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    native.CreateMutexW.restype = wintypes.HANDLE
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    native.CloseHandle.restype = wintypes.BOOL
    handle = native.CreateMutexW(None, False, r"Local\TunnelGuard.Desktop")
    error = ctypes.get_last_error()
    if not handle:
        raise ctypes.WinError(error)
    if error == 183:  # ERROR_ALREADY_EXISTS
        native.CloseHandle(handle)
        raise GuardDenied("TunnelGuard уже запущен на этом рабочем столе.")
    return lambda: native.CloseHandle(handle)


class DesktopGuard:
    def __init__(self, custom_apps=(), catalog_error=None):
        self.lock = RLock()
        self.custom_apps = {app.name: app for app in custom_apps}
        self.catalog_error = catalog_error
        self.configured_paths = {}

    @property
    def applications(self):
        return (*APPLICATIONS, *self.custom_apps)

    def app_path(self, name):
        custom = self.custom_apps.get(name)
        if custom:
            return custom.path if custom.path.is_file() else None
        configured = self.configured_paths.get(name)
        if configured:
            path = Path(configured)
            return path if valid_app_path(name, path) else None
        return find_app(name)

    def running_apps(self):
        if self.catalog_error:
            raise GuardDenied(self.catalog_error)
        apps = tuple(self.custom_apps.values())
        return active_windows_apps(apps) if apps else active_windows_apps()

    def add_app(self, app):
        with self.lock:
            if self.catalog_error:
                raise CatalogError(self.catalog_error)
            apps = (*self.custom_apps.values(), app)
            validate_catalog(apps, APPLICATION_BY_EXE)
            save_catalog(apps)
            self.custom_apps[app.name] = app

    def connect(self, server_ip=DEFAULT_VPN_SERVER_IP):
        with self.lock:
            if current_route() is not None:
                return False
            return amnezia_ui("connect", server_ip=server_ip)["changed"]

    def disconnect(self):
        with self.lock:
            running = [app for app, pids in self.running_apps().items() if pids]
            if running:
                raise GuardDenied("Закрой перед отключением VPN: " + ", ".join(running))
            if self.custom_apps:
                return amnezia_ui("disconnect", custom_apps=tuple(self.custom_apps.values()))["changed"]
            return amnezia_ui("disconnect")["changed"]

    def launch(self, app, target_ip=DEFAULT_TARGET_IP):
        with self.lock:
            if app not in self.applications:
                raise GuardDenied("Неизвестное приложение")
            if target_ip is None:
                raise GuardDenied("Укажи целевой внешний IPv4 в настройках.")
            path = self.app_path(app)
            if path is None:
                raise GuardDenied("Исполняемый файл приложения не найден")
            if self.running_apps()[app]:
                raise GuardDenied("Программа уже работает")
            evidence, _ = probe_windows(target_ip)
            if not evidence.confirmed:
                raise GuardDenied(f"Оба сервиса должны подтвердить IPv4 {target_ip} через AmneziaVPN")
            if current_route() != evidence.route_after:
                raise GuardDenied("Маршрут изменился во время проверки")
            custom = self.custom_apps.get(app)
            terminal = custom.console if custom else app in {"Claude", "Codex CLI", "OpenCode CLI"}
            console = subprocess.CREATE_NEW_CONSOLE if terminal else 0
            # PyInstaller changes the DLL search path for itself and its children.
            bundle = getattr(sys, "_MEIPASS", None)
            if bundle and not ctypes.windll.kernel32.SetDllDirectoryW(None):
                raise ctypes.WinError()
            try:
                return subprocess.Popen([str(path)], cwd=Path.home() if console else path.parent,
                                        creationflags=console, shell=False).pid
            finally:
                if bundle:
                    ctypes.windll.kernel32.SetDllDirectoryW(bundle)
