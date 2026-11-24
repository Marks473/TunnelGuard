from datetime import datetime
import tkinter as tk

from activity import Usage, duration


class ActivityView:
    def open_app_activity(self, name, title):
        if self.busy or self.settings_window is not None:
            return
        p = self.palette
        dialog = tk.Toplevel(self.root)
        self.settings_window = dialog
        dialog.title(f"Статистика · {title}")
        dialog.configure(bg=p.panel, padx=20, pady=16)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        self.label(dialog, title, 19, weight="bold").pack(fill="x")
        body = tk.Frame(dialog, bg=p.panel)
        body.pack(fill="x", pady=(9, 8))
        body.columnconfigure(1, weight=1)
        rows = (
            ("session", "Текущая сессия"), ("today", "Сегодня"), ("week", "Последние 7 дней"),
            ("total", "Всего"), ("starts", "Наблюдаемые запуски"), ("last", "Последняя активность"),
            ("processes", "Процессы сейчас"),
        )
        labels = {}
        for index, (key, caption) in enumerate(rows):
            self.label(body, caption, 10, color=p.muted, pady=3).grid(row=index, column=0, sticky="w", padx=(0, 20))
            value = self.label(body, size=10, weight="bold")
            value.grid(row=index, column=1, sticky="e")
            labels[key] = value
        self.activity_detail = (name, labels)
        self.update_activity_dialog()
        self.label(dialog, "Время считается, пока TunnelGuard видит процессы приложения.",
                   9, color=p.muted, wraplength=335, justify="left").pack(fill="x", pady=(0, 9))

        def close():
            self.activity_detail = None
            self.settings_window = None
            dialog.destroy()

        def show_history():
            close()
            self.select_filter("history")
            self.history_query.set(title)

        actions = tk.Frame(dialog, bg=p.panel)
        actions.pack(fill="x")
        self.button(actions, "История приложения", show_history).pack(side="left")
        self.button(actions, "Готово", close, primary=True).pack(side="right", padx=(6, 0))
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        dialog.wait_visibility()
        dialog.grab_set()

    def update_activity_dialog(self):
        if self.activity_detail is None:
            return
        name, labels = self.activity_detail
        usage = self.activity.records.get(name, Usage())
        today = datetime.now().date()
        running = (self.running or {}).get(name, ())
        values = {
            "session": duration(self.activity.session_seconds.get(name, 0)) if running else "—",
            "today": duration(usage.recent(today, 1)),
            "week": duration(usage.recent(today, 7)),
            "total": duration(usage.total),
            "starts": str(usage.starts),
            "last": datetime.fromtimestamp(usage.last_seen).strftime("%d.%m.%Y %H:%M") if usage.last_seen else "—",
            "processes": str(len(running)) if self.running is not None else "Нет статуса",
        }
        for key, label in labels.items():
            label.config(text=values[key])



    def build_history(self, page):
        p = self.palette
        self.history_page = tk.Frame(page, bg=p.bg)
        header = tk.Frame(self.history_page, bg=p.hero, padx=18, pady=14,
                          highlightthickness=1, highlightbackground=p.hero_edge)
        header.pack(fill="x", pady=(0, 13))
        self.label(header, "История запусков", 22, bg=p.hero, weight="bold").pack(fill="x")
        self.label(header, "Запуски, завершения и проверка VPN", 10, color=p.hero_text, bg=p.hero).pack(fill="x")
        toolbar = tk.Frame(self.history_page, bg=p.bg)
        toolbar.pack(fill="x", pady=(0, 9))
        self.label(toolbar, "Поиск по приложению", 9, color=p.muted, bg=p.bg).pack(side="left", padx=(0, 7))
        self.history_query = tk.StringVar(self.root, value=self.history_filter)
        self.history_search = self.field(toolbar, self.history_query)
        self.history_search.configure(width=23)
        self.history_search.pack(side="left", ipady=4)
        self.history_count = self.label(toolbar, size=9, color=p.muted, bg=p.bg)
        self.history_count.pack(side="right")
        self.history_rows = tk.Frame(self.history_page, bg=p.bg)
        self.history_rows.pack(fill="x")
        self.history_query.trace_add("write", self.filter_history)

    def filter_history(self, *_args):
        self.history_filter = self.history_query.get()
        self.history_limit = 25
        self.render_history_rows()

    def expand_history(self):
        self.history_limit += 25
        self.render_history_rows()

    def update_history_if_visible(self):
        revision = (self.activity.history_revision, self.running is None)
        if self.filter == "history" and self.history_seen_revision != revision:
            self.render_history_rows()

    def render_history_rows(self):
        p = self.palette
        self.history_seen_revision = (self.activity.history_revision, self.running is None)
        for widget in self.history_rows.winfo_children():
            widget.destroy()
        query = self.history_filter.strip().casefold()
        sessions = sorted(
            (session for session in self.activity.history if query in self.display_app_name(session.app).casefold()),
            key=lambda session: session.started_at, reverse=True,
        )
        self.history_count.config(text=f"Записей: {len(sessions)}")
        if not sessions:
            message = "Записи по этому запросу не найдены." if query else "Здесь появятся наблюдаемые запуски приложений."
            self.label(self.history_rows, message, color=p.muted, bg=p.bg, pady=12).pack(fill="x")
            return
        for session in sessions[:self.history_limit]:
            row = tk.Frame(self.history_rows, bg=p.panel, padx=12, pady=8,
                           highlightthickness=1, highlightbackground=p.edge)
            row.pack(fill="x", pady=(0, 6))
            heading = tk.Frame(row, bg=p.panel)
            heading.pack(fill="x")
            self.label(heading, self.display_app_name(session.app), 12, weight="bold").pack(side="left")
            if session.status == "active":
                active = self.running is not None
                state = "●  Работает" if active else "Статус неизвестен"
                color = p.good if active else p.amber
            elif session.status == "closed":
                state, color = "Завершено", p.muted
            else:
                state, color = "Наблюдение прервано", p.amber
            self.label(heading, state, 9, color=color, weight="bold").pack(side="right", padx=(6, 0))
            start_label = {"guarded": "Запуск", "observed": "Запуск замечен",
                           "already_running": "Обнаружено уже открытым"}[session.origin]
            timeline = f"{start_label}: {event_time(session.started_at)}"
            if session.status == "closed":
                timeline += f"  ·  Завершение замечено: {event_time(session.ended_at)}"
            elif session.status == "interrupted":
                timeline += f"  ·  Последний раз замечено: {event_time(session.last_seen)}"
            if session.status != "active" and session.seconds:
                timeline += f"  ·  Наблюдалось {duration(session.seconds)}"
            self.label(row, timeline, 9, color=p.muted, wraplength=550, justify="left").pack(fill="x", pady=(3, 2))
            if session.origin == "guarded":
                note, color = f"✓ VPN и IPv4 проверены при запуске · {session.checked_ip}", p.good
            else:
                note, color = "Проверка VPN при этом запуске не зафиксирована", p.muted
            self.label(row, note, 9, color=color, wraplength=550, justify="left").pack(fill="x")
        if self.history_limit < len(sessions):
            self.button(self.history_rows, "Показать ещё", self.expand_history).pack(anchor="w", pady=5)


def event_time(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d.%m.%Y %H:%M:%S")
