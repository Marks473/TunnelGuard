from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import json
import math
import os
import time
from pathlib import Path

from settings import normalize_ipv4, write_local_json


MAX_SAMPLE_GAP = 12
SAVE_INTERVAL = 30
HISTORY_LIMIT = 400


@dataclass
class Usage:
    total: float = 0
    starts: int = 0
    last_seen: float = 0
    days: dict[str, float] = field(default_factory=dict)

    def recent(self, today, days):
        return sum(self.days.get((today - timedelta(days=offset)).isoformat(), 0) for offset in range(days))


@dataclass
class Session:
    app: str
    started_at: float
    last_seen: float
    origin: str
    status: str = "active"
    ended_at: float = 0
    seconds: float = 0
    checked_ip: str = ""
    pid: int = 0


def activity_path():
    return Path(os.environ["LOCALAPPDATA"]) / "TunnelGuard" / "activity.json"


def load_activity(path=None):
    path = path if path is not None else activity_path()
    try:
        with path.open(encoding="utf-8") as file:
            raw = file.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return ActivityTracker()
        payload = json.loads(raw)
        records = {name: Usage(
            total=nonnegative(value["total"]),
            starts=int(nonnegative(value["starts"])),
            last_seen=timestamp(value["last_seen"]),
            days={date.fromisoformat(day).isoformat(): nonnegative(amount)
                  for day, amount in value["days"].items()},
        ) for name, value in payload.get("usage", {}).items()}
        history = [load_session(row) for row in payload.get("history", [])[:HISTORY_LIMIT]]
        return ActivityTracker(records, history)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return ActivityTracker()


def timestamp(value):
    return nonnegative(value, maximum=time.time() + 24 * 60 * 60)


def load_session(data):
    app = data["app"]
    origin = data["origin"]
    status = data["status"]
    if not isinstance(app, str) or not app or len(app) > 40:
        raise ValueError("Invalid application in activity history")
    if origin not in ("guarded", "observed", "already_running") or status not in ("active", "closed", "interrupted"):
        raise ValueError("Invalid activity history status")
    return Session(
        app=app, started_at=timestamp(data["started_at"]), last_seen=timestamp(data["last_seen"]),
        origin=origin, status="interrupted" if status == "active" else status,
        ended_at=timestamp(data["ended_at"]), seconds=nonnegative(data["seconds"]),
        checked_ip=normalize_ipv4(data["checked_ip"], public=True) if origin == "guarded" else "",
        pid=int(nonnegative(data["pid"])),
    )


def nonnegative(value, maximum=1e12):
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError("Invalid activity value")
    return value


def save_activity(tracker, path=None):
    path = path if path is not None else activity_path()
    write_local_json(path, {
        "usage": {name: asdict(usage) for name, usage in tracker.records.items()},
        "history": [asdict(session) for session in tracker.history[:HISTORY_LIMIT]],
    })


class ActivityTracker:
    def __init__(self, records=None, history=()):
        self.records = records if records is not None else {}
        self.history = list(history)
        self.open_sessions = {}
        self.observed_pids = {}
        self.history_revision = 0
        self.session_seconds = {}
        self.previous = None
        self.dirty = False

    def add_session(self, session):
        self.history.insert(0, session)
        if len(self.history) > HISTORY_LIMIT:
            for index in range(len(self.history) - 1, -1, -1):
                if self.history[index].status != "active":
                    self.history.pop(index)
                    break
        self.open_sessions[session.app] = session
        self.record_change()

    def record_change(self):
        self.history_revision += 1
        self.dirty = True

    def record_guarded_launch(self, app, pid, wall_time, checked_ip):
        session = self.open_sessions.get(app)
        if (session and session.origin != "guarded" and pid in self.observed_pids.get(app, ())
                and abs(wall_time - session.started_at) <= MAX_SAMPLE_GAP):
            session.started_at = min(session.started_at, wall_time)
            session.last_seen = max(session.last_seen, wall_time)
            session.origin, session.checked_ip, session.pid = "guarded", checked_ip, pid
            self.record_change()
            return
        if session:
            self.finish_session(app, "interrupted")
        self.add_session(Session(app, wall_time, wall_time, "guarded", checked_ip=checked_ip, pid=pid))

    def finish_session(self, app, status, ended_at=0):
        session = self.open_sessions.pop(app)
        session.status, session.ended_at = status, ended_at
        self.record_change()

    def end_monitoring(self):
        for app in tuple(self.open_sessions):
            self.finish_session(app, "interrupted")

    def observe(self, processes, *, wall_time, tick):
        if processes is None:
            self.previous = None
            self.observed_pids = {}
            return
        previously_observed = self.observed_pids
        self.observed_pids = {name: frozenset(pids) for name, pids in processes.items() if pids}
        active = {name for name, pids in processes.items() if pids}
        old_wall, old_tick, previous = self.previous or (wall_time, tick, active)
        elapsed = tick - old_tick
        has_interval = 0 < elapsed <= MAX_SAMPLE_GAP
        today = datetime.fromtimestamp(wall_time).date()
        previous_day = datetime.fromtimestamp(old_wall).date()
        oldest = (today - timedelta(days=6)).isoformat()
        new_sessions = {}
        for name, session in tuple(self.open_sessions.items()):
            if name in active:
                if (session.origin == "guarded" and session.pid not in self.observed_pids[name]
                        and (wall_time - session.started_at <= MAX_SAMPLE_GAP)
                        and session.pid not in previously_observed.get(name, ())):
                    self.finish_session(name, "interrupted")
                continue
            recently_spawned = session.origin == "guarded" and 0 <= wall_time - session.started_at <= MAX_SAMPLE_GAP
            ended = has_interval or recently_spawned
            self.finish_session(name, "closed" if ended else "interrupted", wall_time if ended else 0)

        for name in sorted(active):
            usage = self.records.setdefault(name, Usage())
            seconds = self.session_seconds.get(name, 0)
            if name not in previous:
                usage.starts += 1
                seconds = 0
            elif has_interval:
                usage.total += elapsed
                seconds += elapsed
                if previous_day < today and 0 < wall_time - old_wall <= MAX_SAMPLE_GAP:
                    midnight = datetime.combine(today, datetime.min.time()).timestamp()
                    before_midnight = elapsed * (midnight - old_wall) / (wall_time - old_wall)
                    self.add_day(usage, previous_day, before_midnight)
                    self.add_day(usage, today, elapsed - before_midnight)
                else:
                    self.add_day(usage, today, elapsed)
            if name not in self.open_sessions:
                origin = "observed" if self.previous is not None and name not in previous else "already_running"
                self.add_session(Session(name, wall_time, wall_time, origin))
            session = self.open_sessions[name]
            session.last_seen, session.seconds = wall_time, seconds
            usage.last_seen = wall_time
            usage.days = {day: amount for day, amount in usage.days.items() if day >= oldest}
            new_sessions[name] = seconds
            self.dirty = True

        self.session_seconds = new_sessions
        self.previous = wall_time, tick, active

    @staticmethod
    def add_day(usage, day, seconds):
        key = day.isoformat()
        usage.days[key] = usage.days.get(key, 0) + seconds


def duration(seconds):
    seconds = int(seconds)
    hours, minutes = divmod(seconds // 60, 60)
    if hours:
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} с"
