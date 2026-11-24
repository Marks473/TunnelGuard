from dataclasses import dataclass, field
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import tempfile


DEFAULT_TARGET_IP = None
DEFAULT_VPN_SERVER_IP = None
DEFAULT_THEME = "light"
DEFAULT_MINIMIZE_TO_TRAY = True
THEMES = ("light", "dark")


class SettingsError(ValueError):
    pass


def normalize_ipv4(value, *, public=False):
    if not isinstance(value, str):
        raise SettingsError("Введи IPv4 в формате 203.0.113.10, без порта или маски.")
    try:
        address = IPv4Address(value.strip())
    except ValueError as error:
        raise SettingsError("Введи IPv4 в формате 203.0.113.10, без порта или маски.") from error
    if public and (not address.is_global or address.is_multicast or address.is_reserved):
        raise SettingsError("Целевой IPv4 должен быть публичным адресом.")
    return str(address)


@dataclass(frozen=True)
class Settings:
    target_ip: str | None = DEFAULT_TARGET_IP
    vpn_server_ip: str | None = DEFAULT_VPN_SERVER_IP
    theme: str = DEFAULT_THEME
    minimize_to_tray: bool = DEFAULT_MINIMIZE_TO_TRAY
    app_paths: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.target_ip is not None:
            object.__setattr__(self, "target_ip", normalize_ipv4(self.target_ip, public=True))
        if self.vpn_server_ip is not None:
            object.__setattr__(self, "vpn_server_ip", normalize_ipv4(self.vpn_server_ip))
        if not isinstance(self.app_paths, dict) or any(
            not isinstance(name, str) or not isinstance(path, str) for name, path in self.app_paths.items()
        ):
            raise SettingsError("Файл настроек содержит некорректные пути приложений.")
        if self.theme not in THEMES:
            raise SettingsError("Выбери светлую или тёмную тему.")


def settings_path():
    return Path(os.environ["LOCALAPPDATA"]) / "TunnelGuard" / "settings.json"


def load_settings(path=None):
    path = settings_path() if path is None else path
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError) as error:
        raise SettingsError("Не удалось прочитать настройки. Проверь и сохрани адреса заново.") from error
    try:
        if not isinstance(data, dict) or "target_ip" not in data:
            raise SettingsError("Целевой IPv4 отсутствует.")
        theme = data.get("theme", DEFAULT_THEME)
        if theme not in THEMES:
            theme = DEFAULT_THEME
        minimize = data.get("minimize_to_tray", DEFAULT_MINIMIZE_TO_TRAY)
        if type(minimize) is not bool:
            minimize = DEFAULT_MINIMIZE_TO_TRAY
        return Settings(data["target_ip"], data.get("vpn_server_ip"), theme, minimize, data.get("app_paths", {}))
    except SettingsError as error:
        raise SettingsError("Настройки содержат неверный адрес. Проверь и сохрани адреса заново.") from error


def save_settings(settings, path=None):
    path = settings_path() if path is None else path
    write_local_json(path, {
        "target_ip": settings.target_ip, "vpn_server_ip": settings.vpn_server_ip, "theme": settings.theme,
        "minimize_to_tray": settings.minimize_to_tray,
        "app_paths": settings.app_paths,
    })


def write_local_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.stem}-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
