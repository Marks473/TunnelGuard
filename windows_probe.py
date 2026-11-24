import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import http.client
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
from urllib.parse import urlencode

from guard import APPLICATIONS, Evidence, GuardDenied, parse_ip
from settings import DEFAULT_TARGET_IP


VPN_SERVICE = "AmneziaWGTunnel$AmneziaVPN"
VPN_ADAPTER = "AmneziaVPN"
IP_HOSTS = ("api.ipify.org", "checkip.amazonaws.com")
DOH_HOST = "cloudflare-dns.com"
DOH_ADDRESS = "1.1.1.1"
APPLICATION_BY_EXE = {
    "orca.exe": "Orca",
    "claude.exe": "Claude",
    "codex.exe": "Codex CLI",
    "codex-code-mode-host.exe": "Codex CLI",
    "dolphin anty.exe": "Dolphin Anty",
    "dolphin-anty.exe": "Dolphin Anty",
    "dolphin_anty.exe": "Dolphin Anty",
    "code.exe": "Visual Studio Code",
    "opencode.exe": "OpenCode CLI",
}


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("unused_usage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("unused_heap_id", ctypes.c_size_t),
        ("unused_module_id", wintypes.DWORD),
        ("thread_count", wintypes.DWORD),
        ("parent_pid", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("unused_flags", wintypes.DWORD),
        ("exe_name", wintypes.WCHAR * 260),
    ]


def windows_processes():
    if os.name != "nt":
        raise GuardDenied("Список процессов доступен в Windows")

    native = ctypes.WinDLL("kernel32", use_last_error=True)
    native.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    native.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for operation in (native.Process32FirstW, native.Process32NextW):
        operation.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        operation.restype = wintypes.BOOL
    native.CloseHandle.argtypes = [wintypes.HANDLE]
    native.CloseHandle.restype = wintypes.BOOL

    snapshot = native.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    processes = []
    entry = ProcessEntry()
    entry.size = ctypes.sizeof(entry)
    try:
        found = native.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            processes.append((entry.exe_name, entry.pid))
            found = native.Process32NextW(snapshot, ctypes.byref(entry))
        error = ctypes.get_last_error()
        if error != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(error)
    finally:
        native.CloseHandle(snapshot)
    return processes


def active_windows_apps(custom_apps=()):
    custom_processes = {app.path.name.casefold(): app.name for app in custom_apps}
    applications_by_exe = {**APPLICATION_BY_EXE, **custom_processes}
    instances = {name: [] for name in (*APPLICATIONS, *custom_processes.values())}
    for exe_name, pid in windows_processes():
        app = applications_by_exe.get(exe_name.casefold())
        if app:
            instances[app].append(pid)
    return {name: tuple(sorted(pids)) for name, pids in instances.items()}


class ServiceStatus(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in ("service_type", "state", "controls", "win32_error", "service_error",
                     "checkpoint", "wait_hint")
    ]


def service_state(name):
    scm = ctypes.WinDLL("advapi32", use_last_error=True)
    scm.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    scm.OpenSCManagerW.restype = wintypes.HANDLE
    scm.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    scm.OpenServiceW.restype = wintypes.HANDLE
    scm.QueryServiceStatus.argtypes = [wintypes.HANDLE, ctypes.POINTER(ServiceStatus)]
    scm.QueryServiceStatus.restype = wintypes.BOOL
    scm.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    scm.CloseServiceHandle.restype = wintypes.BOOL
    manager = scm.OpenSCManagerW(None, None, 1)  # SC_MANAGER_CONNECT
    if not manager:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        service = scm.OpenServiceW(manager, name, 4)  # SERVICE_QUERY_STATUS
        if not service:
            error = ctypes.get_last_error()
            if error == 1060:  # ERROR_SERVICE_DOES_NOT_EXIST
                return None
            raise ctypes.WinError(error)
        try:
            status = ServiceStatus()
            if not scm.QueryServiceStatus(service, ctypes.byref(status)):
                raise ctypes.WinError(ctypes.get_last_error())
            return status.state
        finally:
            scm.CloseServiceHandle(service)
    finally:
        scm.CloseServiceHandle(manager)


@dataclass(frozen=True)
class Route:
    adapter_id: str
    index: int
    local_ip: str


def powershell_json(command, timeout=5):
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        process = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as error:
        raise GuardDenied("Windows не ответила вовремя. Повтори проверку состояния.") from error
    if process.returncode != 0:
        raise GuardDenied("Windows не выполнила запрос. Проверь доступ к текущему рабочему столу.")
    return json.loads(process.stdout)


def desktop_preflight():
    if os.name != "nt":
        raise GuardDenied("Проверка рабочего стола доступна в Windows")

    status = powershell_json(r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$adminSid = [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$commands = @(Get-Command -Name claude.exe,codex.exe -CommandType Application -All `
    -ErrorAction SilentlyContinue | Select-Object Name, Source)
@{
    account = $identity.Name
    admin_sid_in_token = $identity.Groups.Value -contains $adminSid.Value
    elevated = $principal.IsInRole($adminSid)
    commands = $commands
} | ConvertTo-Json -Depth 3 -Compress
""")
    status["app_identity_running"] = service_state("AppIDSvc") == 4
    status["filtering_engine_running"] = service_state("BFE") == 4
    return status


def current_route():
    if os.name != "nt":
        raise GuardDenied("Диагностика адаптера доступна в Windows")
    if service_state(VPN_SERVICE) != 4:  # SERVICE_RUNNING
        return None

    command = r"""
$ErrorActionPreference = 'Stop'
$adapter = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() |
    Where-Object { $_.Name -ceq 'AmneziaVPN' -and $_.OperationalStatus -eq 'Up' })
if ($adapter.Count -ne 1) { 'null'; exit }
$ipv4 = $adapter[0].GetIPProperties().GetIPv4Properties()
$addresses = @($adapter[0].GetIPProperties().UnicastAddresses | Where-Object {
    $_.Address.AddressFamily -eq 'InterNetwork' -and $_.DuplicateAddressDetectionState -eq 'Preferred'
})
if ($null -eq $ipv4 -or $addresses.Count -ne 1) { 'null'; exit }
@{ id = $adapter[0].Id; index = $ipv4.Index; ip = $addresses[0].Address.ToString() } |
    ConvertTo-Json -Compress
"""
    adapter = powershell_json(command)
    if adapter is None or service_state(VPN_SERVICE) != 4:
        return None
    return Route(adapter["id"], adapter["index"], str(IPv4Address(adapter["ip"])))


def best_interface(address):
    native = ctypes.WinDLL("iphlpapi", use_last_error=True)
    native.GetBestInterface.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    native.GetBestInterface.restype = wintypes.DWORD
    interface = wintypes.DWORD()
    destination, = struct.unpack("=I", socket.inet_aton(address))
    error = native.GetBestInterface(destination, ctypes.byref(interface))
    if error:
        raise ctypes.WinError(error)
    return interface.value


class TunneledHttps(http.client.HTTPSConnection):
    def __init__(self, hostname, remote_ip, route):
        super().__init__(hostname, timeout=5, context=ssl.create_default_context())
        self.remote_ip = remote_ip
        self.route = route

    def connect(self):
        require_tunnel_route(self.route)
        if best_interface(self.remote_ip) != self.route.index:
            raise GuardDenied("Windows выбрала маршрут вне адаптера AmneziaVPN")
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            raw.settimeout(self.timeout)
            # Windows IP_UNICAST_IF takes the interface index in network byte order.
            raw.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", self.route.index))
            raw.bind((self.route.local_ip, 0))
            raw.connect((self.remote_ip, self.port))
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def require_tunnel_route(route):
    if route is None or current_route() != route:
        raise GuardDenied("Туннель AmneziaVPN изменился или недоступен")


def tunneled_get(hostname, remote_ip, route, path, *, accept, max_bytes):
    if route is None:
        raise GuardDenied("Активный туннель AmneziaVPN не найден")
    remote = IPv4Address(remote_ip)
    if not remote.is_global or remote.is_multicast or remote.is_reserved:
        raise GuardDenied("Для HTTPS необходим публичный IPv4")
    connection = TunneledHttps(hostname, str(remote), route)
    try:
        # Connect explicitly so the adapter can be checked again after TLS and before the GET.
        connection.connect()
        require_tunnel_route(route)
        connection.request("GET", path, headers={"Connection": "close", "Accept": accept})
        with connection.getresponse() as response:
            if response.status != 200:
                raise GuardDenied(f"{hostname}: HTTP {response.status}")
            if response.getheader("Content-Encoding", "identity").strip().lower() != "identity":
                raise GuardDenied(f"{hostname}: неподдерживаемое кодирование ответа")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise GuardDenied(f"{hostname}: ответ превышает допустимый размер")
            require_tunnel_route(route)
            return body
    finally:
        connection.close()


def resolve_through_tunnel(hostname, route):
    parameters = urlencode({"name": hostname, "type": "A"})
    body = tunneled_get(DOH_HOST, DOH_ADDRESS, route, "/dns-query?" + parameters,
                        accept="application/dns-json", max_bytes=8192)
    response = json.loads(body)
    if not isinstance(response, dict) or response.get("Status") != 0:
        raise GuardDenied("DNS через VPN не вернул адрес")
    records = response.get("Answer", ())
    if not isinstance(records, list):
        raise GuardDenied("DNS через VPN не вернул IPv4")
    for record in records:
        if isinstance(record, dict) and record.get("type") == 1 and isinstance(record.get("data"), str):
            ip = IPv4Address(record["data"])
            if ip.is_global and not ip.is_multicast and not ip.is_reserved:
                return str(ip)
    raise GuardDenied("DNS через VPN не вернул публичный IPv4")


def query_ip(hostname, route):
    remote_ip = resolve_through_tunnel(hostname, route)
    body = tunneled_get(hostname, remote_ip, route, "/", accept="text/plain", max_bytes=64)
    return parse_ip(body)


def probe_windows(target_ip=DEFAULT_TARGET_IP):
    if target_ip is None:
        raise GuardDenied("Укажи целевой внешний IPv4 в настройках.")
    initial = current_route()
    if initial is None:
        raise GuardDenied("Активный туннель AmneziaVPN не найден")
    results = []
    errors = []
    for hostname in IP_HOSTS:
        try:
            results.append(query_ip(hostname, initial))
        except (GuardDenied, OSError, ValueError, http.client.HTTPException) as error:
            results.append(None)
            errors.append(f"{hostname}: {error}")
    return Evidence(initial, current_route(), tuple(results), target_ip), errors
