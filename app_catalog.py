from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

from guard import APPLICATIONS


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class CustomApp:
    name: str
    path: Path
    console: bool = False

    def __post_init__(self):
        if not isinstance(self.name, str):
            raise CatalogError("Укажи название приложения.")
        name = self.name.strip()
        if not name or len(name) > 40 or any(ord(letter) < 32 for letter in name):
            raise CatalogError("Название должно содержать от 1 до 40 символов.")
        if not self.path.is_absolute() or self.path.suffix.casefold() != ".exe":
            raise CatalogError("Выбери абсолютный путь к файлу .exe.")
        if self.path.drive.startswith("\\\\"):
            raise CatalogError("Выбери файл .exe на локальном диске.")
        if not isinstance(self.console, bool):
            raise CatalogError("Некорректный режим консоли.")
        object.__setattr__(self, "name", name)


def catalog_path():
    return Path(os.environ["LOCALAPPDATA"]) / "TunnelGuard" / "applications.json"


def validate_catalog(apps, built_in_processes):
    names = {name.casefold() for name in (*APPLICATIONS, "Claude Code")}
    executables = set(built_in_processes)
    for app in apps:
        name, executable = app.name.casefold(), app.path.name.casefold()
        if name in names or executable in executables:
            raise CatalogError("Приложение с таким названием или именем EXE уже есть в библиотеке.")
        names.add(name)
        executables.add(executable)


def load_catalog(built_in_processes, path=None):
    path = catalog_path() if path is None else path
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise CatalogError("Ожидался список приложений.")
        apps = tuple(CustomApp(entry["name"], Path(entry["path"]), entry.get("console", False)) for entry in data)
        validate_catalog(apps, built_in_processes)
        return apps
    except FileNotFoundError:
        return ()
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise CatalogError("Не удалось прочитать библиотеку. Проверь файл applications.json.") from error


def save_catalog(apps, path=None):
    path = catalog_path() if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".applications-", delete=False) as file:
            temporary = Path(file.name)
            data = [{"name": app.name, "path": str(app.path), "console": app.console} for app in apps]
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
