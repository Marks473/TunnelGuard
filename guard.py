from dataclasses import dataclass
from ipaddress import IPv4Address
from threading import RLock

from settings import DEFAULT_TARGET_IP

APPLICATIONS = ("Orca", "Claude", "Codex CLI", "Dolphin Anty", "Visual Studio Code", "OpenCode CLI")


class GuardDenied(Exception):
    pass


@dataclass(frozen=True)
class Evidence:
    route_before: object
    route_after: object
    addresses: tuple
    target_ip: str | None = DEFAULT_TARGET_IP

    @property
    def confirmed(self):
        return (
            self.target_ip is not None
            and self.route_before is not None
            and self.route_before == self.route_after
            and self.addresses == (self.target_ip, self.target_ip)
        )


def parse_ip(value):
    value = value.decode("ascii").strip()
    address = IPv4Address(value)
    if str(address) != value:
        raise ValueError("Ожидался IPv4 в стандартной записи")
    return value


class Guard:
    """Serializes controller actions and keeps network access closed on errors."""

    def __init__(self, backend):
        self.backend = backend
        self.lock = RLock()
        self.last_evidence = None

    def snapshot(self):
        with self.lock:
            return self.backend.snapshot(), self.last_evidence

    def connect(self):
        with self.lock:
            self.last_evidence = None
            self.backend.close_access()
            self.backend.connect()

    def disconnect(self):
        with self.lock:
            active = self.backend.active()
            if active is None:
                raise GuardDenied("Список защищённых процессов неизвестен")
            if active:
                raise GuardDenied("Работают: " + ", ".join(active))
            self.last_evidence = None
            self.backend.close_access()
            self.backend.disconnect()

    def _verify_locked(self):
        self.last_evidence = None
        try:
            evidence = self.backend.verify()
            self.last_evidence = evidence
            if not evidence.confirmed:
                raise GuardDenied(f"Маршрут и адрес {evidence.target_ip} не подтверждены")
            return evidence
        except Exception:
            self.backend.close_access()
            raise

    def recheck(self):
        with self.lock:
            evidence = self._verify_locked()
            try:
                active = self.backend.active()
                if active is None:
                    raise GuardDenied("Список защищённых процессов неизвестен")
                if active:
                    self.backend.open_access(evidence.route_after)
            except Exception:
                self.backend.close_access()
                raise
            return evidence

    def launch(self, name):
        if name not in APPLICATIONS:
            raise GuardDenied("Приложение отсутствует в списке")
        with self.lock:
            if self.backend.active() is None:
                raise GuardDenied("Список защищённых процессов неизвестен")
            self.backend.check_launch_available(name)
            evidence = self._verify_locked()
            try:
                self.backend.open_access(evidence.route_after)
                self.backend.launch(name)
            except Exception:
                self.backend.close_access()
                raise


class LabBackend:
    """Deterministic model. All VPN, firewall and application actions are simulated."""

    def __init__(self, target_ip="203.0.113.42"):
        self.target_ip = target_ip
        self.connected = False
        self.access_open = False
        self.running = {}
        self.generation = 0
        self.addresses = (target_ip, target_ip)

    def snapshot(self):
        return self.connected, self.access_open, self.active()

    def active(self):
        return tuple(self.running)

    def connect(self):
        if not self.connected:
            self.generation += 1
            self.connected = True

    def disconnect(self):
        self.close_access()
        self.connected = False
        self.generation += 1

    def close_access(self):
        self.access_open = False

    def open_access(self, route):
        if not self.connected or self.generation != route:
            self.close_access()
            raise GuardDenied("Туннель изменился после проверки")
        self.access_open = True

    def check_launch_available(self, name):
        if name in self.running:
            raise GuardDenied(f"{name} уже работает")

    def launch(self, name):
        self.running[name] = "window"

    def close_window(self, name):
        if name in self.running:
            self.running[name] = "background"

    def finish(self, name):
        self.running.pop(name, None)
        if not self.running:
            self.close_access()

    def verify(self):
        route = self.generation if self.connected else None
        addresses = self.addresses if self.connected else ()
        return Evidence(route, route, addresses, self.target_ip)
