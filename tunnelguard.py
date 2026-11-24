import argparse
from dataclasses import replace
from http.client import HTTPException
import json
from pathlib import Path
import queue
from threading import Thread
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from pywintypes import error as WindowsTrayError

from activity import SAVE_INTERVAL, duration, load_activity, save_activity
from app_catalog import CatalogError, load_catalog
from desktop_control import DesktopGuard, amnezia_ui, autostart_enabled, executable_names, find_app, reserve_desktop_instance, set_autostart, valid_app_path
from guard import APPLICATIONS, GuardDenied
from launcher_view import FONT, PALETTES, LauncherView, app_details
from news_feed import FRESH_SECONDS, MANUAL_SECONDS, RETRY_SECONDS, fetch_news, load_news, save_news, with_translations
from news_translation import translate_titles
from settings import DEFAULT_MINIMIZE_TO_TRAY, DEFAULT_THEME, Settings, SettingsError, load_settings, save_settings
from tray import TrayIcon, TrayStatus, request_open
from windows_probe import APPLICATION_BY_EXE, IP_HOSTS, VPN_ADAPTER, current_route, desktop_preflight, probe_windows


class TunnelGuardWindow(LauncherView):
    def __init__(self, root, startup=False, *, monitor=True):
        self.root = root
        root.title("TunnelGuard")
        root.geometry("1180x806")
        root.minsize(900, 625)
        icon = Path(__file__).with_name("TunnelGuard.ico")
        if icon.is_file():
            root.iconbitmap(default=str(icon))
        catalog_error = None
        try:
            apps = load_catalog(APPLICATION_BY_EXE)
        except CatalogError as error:
            apps, catalog_error = (), str(error)
        self.guard = DesktopGuard(apps, catalog_error)
        self.available = {}
        self.results = queue.Queue()
        self.busy = False
        self.tray = None
        self.tray_visible = False
        self.hidden_in_tray = False
        self.route_known = False
        self.running = None
        self.process_vpn = None
        self.process_check_pending = False
        self.route = None
        self.split = None
        self.ip_confirmed = False
        self.network_check_pending = False
        self.settings_window = None
        self.settings_error = None
        self.activity = load_activity()
        self.history_filter = ""
        self.history_limit = 25
        self.history_seen_revision = -1
        self.activity_detail = None
        self.track_activity = monitor
        self.activity_saved_tick = time.monotonic()
        self.news_cache = load_news()
        self.news_topic = "all"
        self.news_original = False
        self.news_translating = False
        self.news_translation_error = None
        self.news_limit = 30
        self.news_loading = False
        self.news_attempt = None
        self.news_error = None
        try:
            self.settings = load_settings()
        except SettingsError as error:
            self.settings = None
            self.settings_error = str(error)
        if self.settings:
            self.guard.configured_paths = dict(self.settings.app_paths)
        self.palette = PALETTES[self.settings.theme if self.settings else DEFAULT_THEME]
        root.configure(bg=self.palette.bg)
        self.build()
        if catalog_error or self.settings_error:
            self.show_message(catalog_error or self.settings_error, self.palette.amber)
        elif not self.settings.target_ip:
            self.show_message("Первый запуск. Укажи внешний IPv4 VPN в настройках, чтобы включить проверки.")
        root.protocol("WM_DELETE_WINDOW", self.close)
        if monitor:
            self.refresh_processes()
            self.schedule_network_check()
            root.after(100, self.read_results)
            root.after_idle(self.translate_cached_news)
        else:
            self.refresh_process_snapshot(self.read_running_apps(), None, time.time(), time.monotonic())
        if startup and self.settings and self.settings.vpn_server_ip:
            root.after(1500, lambda: self.run_action("Подключение при входе в Windows…", self.connect))

    def close(self):
        minimize = self.settings.minimize_to_tray if self.settings else DEFAULT_MINIMIZE_TO_TRAY
        if minimize:
            self.hide_to_tray()
        else:
            self.exit_launcher()

    def tray_status(self):
        vpn = bool(self.route) if self.route_known else None
        running = None if self.running is None else tuple(
            app_details(app)[0] for app, pids in self.running.items() if pids
        )
        return TrayStatus(self.process_vpn if running else vpn, running)

    def show_tray(self, status):
        if self.tray_visible:
            self.tray.update(status)
            return
        if self.tray is None:
            self.tray = TrayIcon(self.root, self.restore_from_tray, self.exit_launcher)
        self.tray.show(status)
        self.tray_visible = True
        self.tray.notify()

    def hide_to_tray(self):
        if self.settings_window is not None:
            self.settings_window.lift()
            return
        if self.hidden_in_tray:
            return
        try:
            self.show_tray(self.tray_status())
        except (OSError, WindowsTrayError):
            self.show_message("Не удалось открыть трей. Мониторинг продолжается в этом окне.", self.palette.amber)
            return
        self.hidden_in_tray = True
        self.root.after_cancel(self.animation_job)
        self.animation_job = None
        self.root.withdraw()

    def update_tray(self):
        status = self.tray_status()
        if self.hidden_in_tray or status.level == "warning":
            try:
                self.show_tray(status)
            except (OSError, WindowsTrayError):
                self.show_message("Не удалось показать предупреждение в трее. Проверь историю запусков.",
                                  self.palette.danger)
        elif self.tray_visible:
            self.tray.hide()
            self.tray_visible = False

    def restore_from_tray(self):
        was_hidden = self.hidden_in_tray
        self.hidden_in_tray = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.update_tray()
        if was_hidden:
            self.animate()
        self.render_news_status()

    def exit_launcher(self):
        if self.busy:
            if self.hidden_in_tray:
                self.restore_from_tray()
            self.show_message("Дождись завершения текущей операции.", self.palette.amber)
            return
        self.activity.end_monitoring()
        self.flush_activity()
        if self.tray is not None:
            self.tray.close()
        self.root.destroy()

    def open_settings(self):
        if self.busy or self.settings_window is not None:
            return
        dialog = tk.Toplevel(self.root)
        self.settings_window = dialog
        dialog.title("Настройки TunnelGuard")
        dialog.configure(bg=self.palette.panel, padx=20, pady=15)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        fields = self.settings or Settings()
        target = tk.StringVar(dialog, value=fields.target_ip or "")
        server = tk.StringVar(dialog, value=fields.vpn_server_ip or "")
        for title, hint, value in (
            ("Целевой внешний IPv4", "До ввода адреса запуск приложений и обновление новостей закрыты.", target),
            ("IPv4 сервера AmneziaWG", "Нужен для подключения из лаунчера. Может отличаться от внешнего IPv4.", server),
        ):
            self.label(dialog, title, 11, weight="bold").pack(fill="x")
            entry = self.field(dialog, value)
            entry.pack(fill="x", pady=(5, 4), ipady=4)
            if value is target:
                target_entry = entry
            self.label(dialog, hint, color=self.palette.muted).pack(fill="x", pady=(0, 12))
        self.label(dialog, "Тема оформления", 11, weight="bold").pack(fill="x")
        theme = tk.StringVar(dialog, value=fields.theme)
        theme_row = tk.Frame(dialog, bg=self.palette.panel)
        theme_row.pack(fill="x", pady=(5, 12))
        for value, title in (("light", "Светлая"), ("dark", "Тёмная")):
            tk.Radiobutton(
                theme_row, text=title, value=value, variable=theme, indicatoron=False, cursor="hand2",
                font=(FONT, 10, "bold"), relief="flat", bd=0, pady=6,
                bg=self.palette.button, fg=self.palette.text, selectcolor=self.palette.nav_selected,
                activebackground=self.palette.nav_selected, activeforeground=self.palette.text,
                highlightthickness=1, highlightbackground=self.palette.edge, highlightcolor=self.palette.accent,
            ).pack(side="left", fill="x", expand=True, padx=(0, 5))

        minimize = tk.BooleanVar(dialog, value=fields.minimize_to_tray)
        self.checkbox(dialog, "Сворачивать в трей при закрытии", minimize).pack(fill="x")
        self.label(dialog, "Мониторинг продолжится в фоне.", 9, color=self.palette.muted).pack(fill="x", pady=(0, 7))

        self.button(dialog, "Пути приложений…", lambda: self.open_application_paths(dialog)).pack(
            fill="x", pady=(0, 8))
        self.auto = tk.BooleanVar(dialog, value=autostart_enabled())
        self.checkbox(dialog, "Запускать при входе в Windows", self.auto, self.toggle_autostart).pack(fill="x")
        error_label = self.label(dialog, self.settings_error or "", color=self.palette.amber, wraplength=430, justify="left")
        error_label.pack(fill="x")

        def close():
            self.settings_window = None
            dialog.destroy()

        def apply():
            try:
                paths = self.settings.app_paths if self.settings else {}
                new_settings = Settings(target.get().strip() or None, server.get().strip() or None,
                                        theme.get(), minimize.get(), paths)
                save_settings(new_settings)
            except (SettingsError, OSError) as error:
                message = str(error) if isinstance(error, SettingsError) else "Windows не сохранила настройки."
                error_label.config(text=message)
                return
            if self.settings is None or self.settings.target_ip != new_settings.target_ip:
                self.ip_confirmed = False
            self.settings = new_settings
            self.settings_error = None
            close()
            self.apply_theme(new_settings.theme)
            self.update_ip_label()
            self.update_buttons()
            self.show_message("Настройки сохранены.")

        buttons = tk.Frame(dialog, bg=self.palette.panel)
        buttons.pack(anchor="e", pady=(9, 0))
        self.button(buttons, "Отмена", close).pack(side="left", padx=(0, 8))
        self.button(buttons, "Сохранить", apply, primary=True).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        dialog.bind("<Return>", lambda _event: apply())
        dialog.wait_visibility()
        dialog.grab_set()
        target_entry.focus_set()
        target_entry.select_range(0, "end")

    def open_application_paths(self, parent):
        dialog = tk.Toplevel(parent)
        dialog.title("Пути приложений")
        dialog.transient(parent)
        dialog.configure(bg=self.palette.panel, padx=20, pady=15)
        dialog.resizable(False, False)
        self.label(dialog, "Установленные приложения", 15, weight="bold").pack(fill="x")
        self.label(dialog, "Пустое поле включает автоопределение. Для ручной настройки выбери исполняемый файл.",
                   9, color=self.palette.muted, wraplength=620, justify="left").pack(fill="x", pady=(3, 9))
        table = tk.Frame(dialog, bg=self.palette.panel)
        table.pack(fill="x")
        paths = self.guard.configured_paths

        def choose(app, field):
            names = executable_names(app)
            selected = filedialog.askopenfilename(parent=dialog, title=f"Выбери {app_details(app)[0]}",
                                                  filetypes=[("Исполняемые файлы приложения", names)])
            if selected:
                field.set(selected)

        variables = {}
        for row, app in enumerate(APPLICATIONS):
            self.label(table, app_details(app)[0], weight="bold").grid(row=2 * row, column=0, sticky="w", padx=(0, 12))
            value = tk.StringVar(dialog, value=paths.get(app, ""))
            variables[app] = value
            entry = self.field(table, value)
            entry.config(width=49)
            entry.grid(row=2 * row, column=1, sticky="ew", pady=3, ipady=3)
            self.button(table, "Обзор…", lambda name=app, field=value: choose(name, field), compact=True).grid(
                row=2 * row, column=2, padx=(6, 0))
            try:
                located = find_app(app)
            except OSError:
                located = None
            description = "Авто: " + str(located) if located else "Авто: файл не найден"
            self.label(table, description, 8, color=self.palette.muted, wraplength=397, justify="left").grid(
                row=2 * row + 1, column=1, sticky="w", pady=(0, 2))
        error = self.label(dialog, self.settings_error or "", 9, color=self.palette.amber,
                           wraplength=620, justify="left")
        error.pack(fill="x")

        def close():
            dialog.destroy()
            parent.grab_set()
            parent.lift()

        def apply():
            if self.settings is None:
                error.config(text="Сначала сохрани корректные настройки VPN в предыдущем окне.")
                return
            configured = {name: value.get().strip() for name, value in variables.items() if value.get().strip()}
            for name, filename in configured.items():
                try:
                    valid = valid_app_path(name, Path(filename))
                except (OSError, ValueError):
                    valid = False
                if not valid:
                    names = ", ".join(executable_names(name))
                    error.config(text=f"{app_details(name)[0]} · выбери существующий локальный файл {names}.")
                    return
            updated = replace(self.settings, app_paths=configured)
            try:
                save_settings(updated)
            except OSError:
                error.config(text="Windows не сохранила пути приложений.")
                return
            self.settings = updated
            self.guard.configured_paths = dict(configured)
            self.refresh_app_paths()
            self.update_buttons()
            self.show_message("Пути приложений сохранены.")
            close()

        actions = tk.Frame(dialog, bg=self.palette.panel)
        actions.pack(anchor="e", pady=(9, 0))
        self.button(actions, "Отмена", close).pack(side="left", padx=(0, 7))
        self.button(actions, "Сохранить пути", apply, primary=True).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        dialog.wait_visibility()
        dialog.grab_set()

    def apply_theme(self, theme):
        palette = PALETTES[theme]
        if self.palette == palette:
            return

        query, selected = self.search.get(), self.filter
        self.root.after_cancel(self.animation_job)
        self.shell.destroy()
        self.status_bar.destroy()
        self.palette = palette
        self.root.configure(bg=palette.bg)
        self.build()
        self.search.set(query)
        self.select_filter(selected)
        self.render_network()

    def toggle_autostart(self):
        try:
            set_autostart(self.auto.get())
        except OSError:
            self.auto.set(not self.auto.get())
            self.show_message("Windows не сохранила настройку автозапуска.", self.palette.amber)

    def show_message(self, message, color=None):
        self.message.config(text=message, fg=color or self.palette.muted)

    def update_buttons(self):
        can_edit = not self.busy
        self.set_button(self.settings_button, can_edit)
        self.set_button(self.add_button, can_edit and not self.guard.catalog_error)
        active = [app_details(name)[0] for name, pids in (self.running or {}).items() if pids]
        self.set_button(self.disconnect_button, can_edit and self.route and self.running is not None and not active)
        if self.route and self.running is None:
            notice = "Отключение недоступно · статус процессов неизвестен"
        elif self.route and active:
            notice = "Выключение заблокировано. Работают: " + ", ".join(active[:2])
            if len(active) > 2:
                notice += f" и ещё {len(active) - 2}"
        else:
            notice = ""
        self.show_network_note(self.disconnect_note, notice)
        self.set_button(self.connect_button, can_edit and not self.route
                        and self.settings is not None and self.settings.vpn_server_ip is not None)
        self.set_button(self.ip_button, self.route and can_edit and self.target_ip is not None)
        self.refresh_cards()

    def show_network_note(self, widget, message):
        widget.config(text=message)
        if message:
            widget.pack(fill="x", pady=(3, 0))
        else:
            widget.pack_forget()

    def refresh_cards(self):
        for app, label in self.app_labels.items():
            running = self.running.get(app, ()) if self.running is not None else ()
            available = self.available.get(app)
            if self.running is None:
                text, color = "●  Нет статуса", self.palette.amber
            elif running:
                session = self.activity.session_seconds.get(app, 0)
                text, color = duration(session), self.palette.good
            elif available:
                text, color = "●  Установлено", self.palette.muted
            else:
                text, color = "●  Не найдено", self.palette.amber
            label.config(text=text, fg=color)
            _, badge, summary = self.app_tiles[app]
            if running:
                badge.place(relx=1, x=-8, y=8, anchor="ne")
            else:
                badge.place_forget()
            usage = self.activity.records.get(app)
            summary.config(text=f"Всего {duration(usage.total if usage else 0)}")
            self.outline_app_tile(app, self.palette.edge)
            self.set_button(self.launch_buttons[app], available and not running and self.running is not None
                            and self.target_ip is not None and self.route and not self.busy)

    def read_running_apps(self):
        try:
            return self.guard.running_apps()
        except (OSError, GuardDenied):
            return None

    def refresh_app_paths(self):
        for app in self.guard.applications:
            try:
                self.available[app] = self.guard.app_path(app) is not None
            except OSError:
                self.available[app] = False

    def refresh_process_snapshot(self, running, vpn, wall_time, tick):
        self.process_check_pending = False
        self.running = running
        self.process_vpn = vpn
        self.refresh_app_paths()
        if self.track_activity:
            incident_changed = self.activity.observe(running, wall_time=wall_time, tick=tick, vpn=vpn)
            if incident_changed or tick - self.activity_saved_tick >= SAVE_INTERVAL:
                self.flush_activity()
        self.update_buttons()
        self.update_activity_dialog()
        self.update_history_if_visible()
        self.update_tray()

    def flush_activity(self):
        if not self.activity.dirty:
            return
        self.activity_saved_tick = time.monotonic()
        try:
            save_activity(self.activity)
        except OSError:
            return
        self.activity.dirty = False

    def refresh_processes(self):
        if not self.process_check_pending:
            self.process_check_pending = True

            def sample():
                running = self.read_running_apps()
                vpn = None
                if running and any(running.values()):
                    try:
                        vpn = current_route() is not None
                    except (OSError, GuardDenied, ValueError):
                        pass
                    if vpn is False:
                        running = self.read_running_apps()
                self.results.put(("processes", (running, vpn, time.time(), time.monotonic())))

            Thread(target=sample, daemon=True).start()
        self.root.after(2000, self.refresh_processes)

    def schedule_network_check(self):
        if not self.network_check_pending and not self.busy:
            self.network_check_pending = True

            def read_network():
                route = split = None
                route_known = False
                try:
                    route = current_route()
                    route_known = True
                    if route:
                        split = amnezia_ui("inspect")["split"]
                except (GuardDenied, OSError, ValueError):
                    pass
                self.results.put(("network", (route, split, route_known)))

            Thread(target=read_network, daemon=True).start()
        self.root.after(5500, self.schedule_network_check)

    def update_network(self, route, split, route_known=True):
        self.network_check_pending = False
        if route != self.route:
            self.ip_confirmed = False
        self.route, self.split = route, split
        self.route_known = route_known
        self.render_network()
        self.update_tray()
        self.refresh_news(automatic=True)

    def render_network(self):
        route, split = self.route, self.split
        color = self.palette.good if route else self.palette.amber
        self.vpn_label.config(text="●  Туннель активен" if route else "●  Туннель не подтверждён", fg=color)
        self.hero_status.config(text="●  AmneziaVPN активен" if route else "●  Туннель не подтверждён", fg=color)
        notice = "Раздельное туннелирование · действуют правила Amnezia" if route and split == "on" else ""
        self.show_network_note(self.split_label, notice)
        self.update_ip_label()
        self.update_buttons()
        self.render_news_status()

    @property
    def target_ip(self):
        return self.settings.target_ip if self.settings else None

    def update_ip_label(self):
        if self.target_ip is None:
            self.ip_label.config(text="Целевой IPv4 не задан · проверь настройки", fg=self.palette.amber)
            return
        label = "Подтверждённый IPv4" if self.ip_confirmed else "Целевой IPv4"
        self.ip_label.config(text=f"{label}\n{self.settings.target_ip}", fg=self.palette.good if self.ip_confirmed else self.palette.muted)

    def can_refresh_news(self, *, automatic=False):
        if (self.hidden_in_tray or not self.route or self.target_ip is None or self.news_loading
                or self.busy or self.settings_window is not None):
            return False
        if automatic and time.time() - self.news_cache.fetched_at < FRESH_SECONDS:
            return False
        interval = RETRY_SECONDS if automatic else MANUAL_SECONDS
        return self.news_attempt is None or time.monotonic() - self.news_attempt >= interval

    def news_update_status(self):
        if self.news_translating:
            return "Переводим заголовки на этом компьютере…"
        if self.news_translation_error:
            return self.news_translation_error
        if not self.route:
            return "Лента обновляется только через активный AmneziaVPN."
        if self.target_ip is None:
            return "Задай целевой IPv4 в настройках, чтобы обновить ленту."
        if self.news_loading:
            return "Проверяем IPv4 и загружаем новости через VPN…"
        if self.news_error:
            return self.news_error
        if not self.news_cache.articles:
            return "Ожидаем первую подборку новостей через VPN."
        if not self.can_refresh_news():
            return "Автообновление раз в час. Повторный ручной запрос доступен через две минуты."
        return "Автообновление раз в час через VPN."

    def refresh_news(self, *, automatic=False):
        if not self.can_refresh_news(automatic=automatic):
            return
        target, route = self.target_ip, self.route
        self.news_loading = True
        self.news_attempt = time.monotonic()
        self.news_error = None
        self.render_news_status()

        def read_feed():
            cache, error = None, None
            try:
                cache = fetch_news(target)
            except GuardDenied as problem:
                error = str(problem)
            except (OSError, ValueError, HTTPException):
                error = "Ленту пока не удалось загрузить через VPN."
            self.results.put(("news", (target, route, cache, error)))

        Thread(target=read_feed, daemon=True).start()

    def receive_news(self, target, route, cache, error):
        self.news_loading = False
        if self.target_ip != target or self.route != route:
            self.render_news_status()
            return
        self.news_error = error
        if cache is None:
            self.render_news_status()
            return
        previous_titles = {
            item.title: item.russian_title for item in self.news_cache.articles if item.russian_title
        }
        self.news_cache = with_translations(cache, previous_titles)
        self.persist_news_cache()
        self.render_news()
        self.translate_cached_news()

    def persist_news_cache(self):
        try:
            save_news(self.news_cache)
        except OSError:
            self.news_error = "Новости загружены, но локальный кэш не сохранился."

    def translate_cached_news(self):
        if self.news_translating:
            return
        cache = self.news_cache
        pending = tuple(item.title for item in cache.articles if not item.russian_title)
        if not pending:
            return
        self.news_translating = True
        self.news_translation_error = None
        self.render_news_status()

        def translate():
            try:
                result = translate_titles(pending)
            except (ImportError, OSError, RuntimeError, ValueError):
                result = None
            self.results.put(("news_translation", (cache.fetched_at, result)))

        Thread(target=translate, daemon=True).start()

    def receive_translations(self, fetched_at, translations):
        self.news_translating = False
        if translations is None:
            self.news_translation_error = "Локальный перевод недоступен. Показываем оригинальные заголовки."
            self.render_news_status()
            return

        cache = with_translations(self.news_cache, translations)
        if cache is not self.news_cache:
            self.news_cache = cache
            self.persist_news_cache()
            self.render_news()
        else:
            self.render_news_status()
        if fetched_at != self.news_cache.fetched_at:
            self.translate_cached_news()

    def start_app(self, name):
        self.run_action(f"Проверяем условия запуска {app_details(name)[0]}…", lambda: self.launch(name))

    def run_action(self, message, function):
        if self.busy or self.settings_window is not None:
            return
        self.busy = True
        self.update_buttons()
        self.show_message(message)

        def worker():
            try:
                self.results.put(("action", (function(), True)))
            except (OSError, ValueError, GuardDenied) as error:
                self.results.put(("action", (str(error), False)))
            except Exception:
                self.results.put(("action", ("Windows не завершила операцию. Повтори проверку состояния.", False)))

        Thread(target=worker, daemon=True).start()

    def read_results(self):
        while not self.results.empty():
            kind, value = self.results.get_nowait()
            if kind == "network":
                self.update_network(*value)
                continue
            if kind == "processes":
                self.refresh_process_snapshot(*value)
                continue
            if kind == "news":
                self.receive_news(*value)
                continue
            if kind == "news_translation":
                self.receive_translations(*value)
                continue
            if kind == "guarded_launch":
                self.activity.record_guarded_launch(*value)
                self.flush_activity()
                self.update_history_if_visible()
                continue
            self.busy = False
            result, success = value
            if success:
                message, ip_confirmed = result
                if ip_confirmed is not None:
                    self.ip_confirmed = ip_confirmed
            else:
                message = result
                self.ip_confirmed = False
            self.update_ip_label()
            self.show_message(message, self.palette.muted if success else self.palette.amber)
            self.update_buttons()
        self.root.after(100, self.read_results)

    def connect(self):
        if self.settings is None:
            raise GuardDenied(self.settings_error)
        changed = self.guard.connect(self.settings.vpn_server_ip)
        return ("Команда подключения отправлена в AmneziaVPN." if changed else "VPN уже подключён."), None

    def disconnect(self):
        changed = self.guard.disconnect()
        return ("Команда отключения отправлена в AmneziaVPN." if changed else "VPN уже отключён."), False

    def check_ip(self):
        evidence, errors = probe_windows(self.target_ip)
        summary = "  ·  ".join(f"{host} {ip or 'нет ответа'}" for host, ip in zip(IP_HOSTS, evidence.addresses))
        if not evidence.confirmed:
            raise GuardDenied("IP не подтверждён. " + (errors[0] if errors else summary))
        return "Две проверки IPv4 пройдены. " + summary, True

    def launch(self, app):
        target = self.target_ip
        pid = self.guard.launch(app, target)
        self.results.put(("guarded_launch", (app, pid, time.time(), target)))
        return f"{app_details(app)[0]} запущен после проверки VPN и IPv4.", True


def main():
    parser = argparse.ArgumentParser(description="TunnelGuard — лаунчер с проверкой AmneziaVPN")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="проверить адаптер без сетевых запросов")
    modes.add_argument("--preflight", action="store_true", help="проверить права и команды Windows")
    modes.add_argument("--startup", action="store_true", help="подключить VPN при входе в Windows")
    modes.add_argument("--verify-build", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.preflight:
        status = desktop_preflight()
        status["opencode_cli_installed"] = find_app("OpenCode CLI") is not None
        print(json.dumps(status, ensure_ascii=True, indent=2))
        return
    if args.status:
        route = current_route()
        print(f"{VPN_ADAPTER}: {'active' if route else 'unavailable'}")
        print(f"Orca executable: {'exists' if find_app('Orca') else 'missing'}")
        return
    root = tk.Tk()
    if args.verify_build:
        root.withdraw()
        window = TunnelGuardWindow(root, monitor=False)
        root.update_idletasks()
        if window.running is None:
            raise RuntimeError("Windows process snapshot failed")
        if not translate_titles(("The model is now available",)):
            raise RuntimeError("Offline Russian translation failed")
        root.destroy()
        return
    try:
        release = reserve_desktop_instance()
    except (OSError, GuardDenied) as error:
        if not args.startup and not request_open():
            messagebox.showinfo("TunnelGuard", str(error), parent=root)
        root.destroy()
        return
    try:
        TunnelGuardWindow(root, startup=args.startup)
        root.mainloop()
    finally:
        release()


if __name__ == "__main__":
    main()
