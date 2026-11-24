from dataclasses import dataclass
from math import tau
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import ImageTk

from activity_view import ActivityView
from app_catalog import CatalogError, CustomApp
from launcher_art import brand_icon, card_art, launch_art, orbit
from news_view import NewsView


FONT = "Segoe UI"


@dataclass(frozen=True)
class Palette:
    is_light: bool
    bg: str
    sidebar: str
    panel: str
    edge: str
    text: str
    muted: str
    accent: str
    good: str
    amber: str
    hero: str
    hero_edge: str
    hero_text: str
    badge: str
    spark: str
    status_bar: str
    primary: str
    primary_hover: str
    primary_text: str
    button: str
    button_hover: str
    disabled: str
    disabled_text: str
    entry: str
    selection: str
    nav: str
    nav_selected: str
    scrollbar: str


PALETTES = {
    "light": Palette(
        is_light=True, bg="#f8f7fc", sidebar="#f0edf7", panel="#ffffff", edge="#ded8ea",
        text="#241b35", muted="#5c556d", accent="#6340b4", good="#08744e", amber="#8e4a23",
        hero="#eee7ff", hero_edge="#d7c6f2", hero_text="#514565", badge="#e2d7f7", spark="#aa5b5e",
        status_bar="#ede8f6", primary="#6542bc", primary_hover="#54369d", primary_text="#ffffff",
        button="#eee8f7", button_hover="#e3d9f4", disabled="#f3f0f6", disabled_text="#746b82",
        entry="#ffffff", selection="#623ea7", nav="#e9e4f3", nav_selected="#dfd1f8", scrollbar="#c2b4d3",
    ),
    "dark": Palette(
        is_light=False, bg="#101017", sidebar="#14141e", panel="#1b1b27", edge="#303043",
        text="#f5f2ff", muted="#a8a5bc", accent="#c5afff", good="#8de1bd", amber="#ffc695",
        hero="#1b1730", hero_edge="#3e3155", hero_text="#c7bfdc", badge="#2a2142", spark="#f9c4ae",
        status_bar="#191823", primary="#bda7ff", primary_hover="#daccff", primary_text="#21173e",
        button="#28273b", button_hover="#393650", disabled="#252435", disabled_text="#9390a4",
        entry="#151520", selection="#675199", nav="#1d1c2a", nav_selected="#34284c", scrollbar="#37354b",
    ),
}


APP_DETAILS = {
    "Orca": ("Orca", "Рабочие пространства для агентов", "#a895fe", "orbit", "ai"),
    "Claude": ("Claude Code", "ИИ-агент в терминале", "#f3a989", "spark", "ai"),
    "Codex CLI": ("Codex CLI", "ИИ-агент в терминале", "#79dac1", "terminal", "ai"),
    "OpenCode CLI": ("OpenCode CLI", "ИИ-агент в терминале", "#ead694", "pixels", "ai"),
    "Dolphin Anty": ("Dolphin Anty", "Профили браузера", "#ed9ecb", "wave", "desktop"),
    "Visual Studio Code": ("Visual Studio Code", "Редактор кода", "#83c7fa", "code", "desktop"),
}


def app_details(name):
    return APP_DETAILS.get(name, (name, "Добавлено в библиотеку", "#c5afff", "custom", "custom"))


class LauncherView(NewsView, ActivityView):
    def label(self, parent, text="", size=10, color=None, bg=None, weight="normal", **options):
        return tk.Label(parent, text=text, font=(FONT, size, weight), fg=color or self.palette.text,
                        bg=bg or self.palette.panel,
                        anchor="w", **options)

    def button(self, parent, text, command, primary=False, *, compact=False):
        palette = self.palette
        normal, hover = (palette.primary, palette.primary_hover) if primary else (palette.button, palette.button_hover)
        foreground = palette.primary_text if primary else palette.text
        button = tk.Button(parent, text=text, command=command, font=(FONT, 9 if compact else 10, "bold"),
                           relief="flat", bd=0, padx=12, pady=5 if compact else 7, cursor="hand2",
                           highlightthickness=1, highlightbackground=normal, highlightcolor=self.palette.accent,
                           bg=normal, fg=foreground, activebackground=hover,
                           activeforeground=foreground, disabledforeground=palette.disabled_text)
        button.normal_bg = normal
        button.bind("<Enter>", lambda _event: button.config(
            bg=hover if button["state"] == "normal" else self.palette.disabled))
        button.bind("<Leave>", lambda _event: button.config(
            bg=button.normal_bg if button["state"] == "normal" else self.palette.disabled))
        return button

    def set_button(self, button, enabled):
        state = "normal" if enabled else "disabled"
        if button["state"] != state:
            button.config(state=state, bg=button.normal_bg if enabled else self.palette.disabled,
                          highlightbackground=button.normal_bg if enabled else self.palette.disabled,
                          cursor="hand2" if enabled else "arrow")

    def field(self, parent, value):
        palette = self.palette
        return tk.Entry(parent, textvariable=value, bg=palette.entry, fg=palette.text, insertbackground=palette.text,
                        selectbackground=palette.selection, selectforeground="#ffffff", relief="flat", font=(FONT, 11),
                        highlightthickness=1, highlightbackground=self.palette.edge, highlightcolor=self.palette.accent)

    def build(self):
        shell = self.shell = tk.Frame(self.root, bg=self.palette.bg)
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=self.palette.sidebar, width=235)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Frame(shell, bg=self.palette.edge, width=1).pack(side="left", fill="y")
        self.build_sidebar(sidebar)

        main = tk.Frame(shell, bg=self.palette.bg)
        main.pack(side="left", fill="both", expand=True)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Library.Vertical.TScrollbar", background=self.palette.scrollbar, troughcolor=self.palette.bg,
                        bordercolor=self.palette.bg, lightcolor=self.palette.scrollbar, darkcolor=self.palette.scrollbar,
                        arrowcolor=self.palette.muted, arrowsize=10)
        self.viewport = tk.Canvas(main, bg=self.palette.bg, bd=0, highlightthickness=0, yscrollincrement=22)
        self.viewport.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(main, command=self.viewport.yview, style="Library.Vertical.TScrollbar")
        def sync_scrollbar(first, last):
            scrollbar.set(first, last)
            if float(first) == 0 and float(last) == 1:
                scrollbar.place_forget()
            else:
                scrollbar.place(relx=1, rely=0, relheight=1, anchor="ne")

        self.viewport.configure(yscrollcommand=sync_scrollbar)
        page = tk.Frame(self.viewport, bg=self.palette.bg, padx=25, pady=20)
        window_id = self.viewport.create_window(0, 0, window=page, anchor="nw")
        page.bind("<Configure>", lambda _event: self.viewport.configure(scrollregion=self.viewport.bbox("all")))
        self.viewport.bind("<Configure>", lambda event: self.resize_library(window_id, event.width))
        self.root.bind("<MouseWheel>", self.scroll_library)

        self.hero_panel = self.build_hero(page)
        self.build_news(page)
        self.build_history(page)
        self.library = tk.Frame(page, bg=self.palette.bg)
        toolbar = tk.Frame(self.library, bg=self.palette.bg)
        toolbar.pack(fill="x", pady=(19, 11))
        self.section_title = self.label(toolbar, "Библиотека", 19, bg=self.palette.bg, weight="bold")
        self.section_title.pack(side="left")
        self.count = self.label(toolbar, bg=self.palette.bg, color=self.palette.muted, padx=10)
        self.count.pack(side="left")
        self.add_button = self.button(toolbar, "+  Добавить", self.open_add_app, primary=True, compact=True)
        self.add_button.pack(side="right")
        self.search = tk.StringVar(self.root)
        search = self.field(toolbar, self.search)
        search.configure(width=17)
        search.pack(side="right", ipady=4, padx=(0, 9))
        self.label(toolbar, "Поиск", 9, self.palette.muted, self.palette.bg, padx=8).pack(side="right")
        def focus_search(_event):
            if self.filter == "history":
                self.history_search.focus_set()
            elif self.filter != "news":
                search.focus_set()

        self.root.bind("<Control-f>", focus_search)
        search.bind("<Escape>", lambda _event: self.search.set(""))

        self.cards = tk.Frame(self.library, bg=self.palette.bg)
        self.cards.pack(fill="x")
        self.app_labels = {}
        self.launch_buttons = {}
        self.app_tiles = {}
        self.columns = 3
        self.filter = "all"
        self.images = {}
        self.select_filter("all")
        self.search.trace_add("write", lambda *_args: self.render_library())

        status_bar = self.status_bar = tk.Frame(self.root, bg=self.palette.status_bar, padx=18, pady=7)
        status_bar.pack(side="bottom", fill="x", before=shell)
        self.progress = tk.Canvas(status_bar, width=18, height=16, bg=self.palette.status_bar, highlightthickness=0)
        self.progress.pack(side="left")
        self.progress_item = self.progress.create_arc(3, 3, 13, 13, style="arc", width=2, outline=self.palette.accent, extent=300)
        self.message = self.label(status_bar, "Перед каждым запуском TunnelGuard проверяет VPN и IPv4.",
                                  9, self.palette.muted, self.palette.status_bar, justify="left")
        self.message.pack(side="left", fill="x", expand=True)
        status_bar.bind("<Configure>", lambda event: self.message.config(wraplength=max(100, event.width - 60)))
        self.animate()

    def build_sidebar(self, sidebar):
        inner = tk.Frame(sidebar, bg=self.palette.sidebar, padx=15, pady=20)
        inner.pack(fill="both", expand=True)
        brand = tk.Frame(inner, bg=self.palette.sidebar)
        brand.pack(fill="x", pady=(0, 19))
        self.logo_photo = ImageTk.PhotoImage(brand_icon(40), master=self.root)
        tk.Label(brand, image=self.logo_photo, bg=self.palette.sidebar, bd=0).pack(side="left", padx=(0, 8))
        self.label(brand, "TunnelGuard", 16, bg=self.palette.sidebar, weight="bold").pack(side="left")
        self.nav = {}
        self.filters = (
            ("all", "Главная", "⌂"), ("news", "Новости ИИ", "▤"), ("history", "История", "◷"),
            ("ai", "ИИ-инструменты", "✧"), ("desktop", "Программы Windows", "▣"),
            ("custom", "Мои приложения", "+"),
        )
        for key, title, glyph in self.filters:
            button = self.button(inner, f"  {glyph}    {title}", lambda selected=key: self.select_filter(selected))
            button.configure(anchor="w", padx=7, pady=6)
            button.pack(fill="x", pady=(0, 4))
            self.nav[key] = button

        bottom = tk.Frame(inner, bg=self.palette.sidebar)
        bottom.pack(side="bottom", fill="x")
        network = tk.Frame(bottom, bg=self.palette.panel, padx=11, pady=11,
                           highlightbackground=self.palette.edge, highlightthickness=1)
        network.pack(fill="x", pady=(0, 9))
        self.label(network, "AmneziaVPN", 12, weight="bold").pack(fill="x")
        self.vpn_label = self.label(network, "●  Проверяем туннель…", 9, color=self.palette.muted,
                                    justify="left", wraplength=175)
        self.vpn_label.pack(fill="x", pady=(3, 3))
        self.ip_label = self.label(network, size=9, color=self.palette.muted, justify="left", wraplength=175)
        self.ip_label.pack(fill="x", pady=(0, 3))
        self.update_ip_label()
        self.split_label = self.label(network, size=8, color=self.palette.amber, justify="left", wraplength=175)
        self.disconnect_note = self.label(network, size=8, color=self.palette.muted, justify="left", wraplength=175)
        self.ip_button = self.button(network, "Проверить IPv4",
                                     lambda: self.run_action("Проверяем IPv4 через VPN…", self.check_ip), compact=True)
        self.ip_button.pack(fill="x", pady=(7, 4))
        actions = tk.Frame(network, bg=self.palette.panel)
        actions.pack(fill="x")
        self.connect_button = self.button(actions, "Включить",
                                          lambda: self.run_action("Подключение VPN…", self.connect), compact=True)
        self.disconnect_button = self.button(actions, "Выключить",
                                             lambda: self.run_action("Проверяем процессы…", self.disconnect), compact=True)
        for button in (self.connect_button, self.disconnect_button):
            button.configure(padx=4)
            button.pack(side="left", fill="x", expand=True, padx=1)
        self.settings_button = self.button(bottom, "Настройки", self.open_settings, compact=True)
        self.settings_button.pack(fill="x")

    def build_hero(self, page):
        banner = tk.Frame(page, bg=self.palette.hero, height=214, highlightthickness=1, highlightbackground=self.palette.hero_edge)
        banner.pack_propagate(False)
        self.orbit_photo = ImageTk.PhotoImage(launch_art(self.palette.hero, self.palette.is_light), master=self.root)
        self.hero_art = tk.Canvas(banner, height=214, width=450, bg=self.palette.hero, highlightthickness=0)
        self.hero_art.place(relx=1, rely=.5, anchor="e")
        self.hero_art.create_image(0, 0, anchor="nw", image=self.orbit_photo)
        self.spark = self.hero_art.create_oval(0, 0, 5, 5, fill=self.palette.spark, outline="")
        intro = tk.Frame(banner, bg=self.palette.hero)
        intro.place(x=21, rely=.5, anchor="w")
        self.label(intro, "Рабочая станция", 27, bg=self.palette.hero, weight="bold").pack(anchor="w")
        self.label(intro, "Запускай ИИ-агентов и приложения\nчерез проверенное VPN-подключение.",
                   11, self.palette.hero_text, self.palette.hero, justify="left").pack(anchor="w", pady=(5, 14))
        self.hero_status = self.label(intro, "●  Проверяем AmneziaVPN", 9, self.palette.accent, self.palette.badge, padx=8, pady=4)
        self.hero_status.pack(anchor="w")
        return banner

    def animate(self):
        phase = time.monotonic()
        x, y = orbit(115, phase * tau / 12, (288, 108))
        self.hero_art.coords(self.spark, x - 2, y - 2, x + 2, y + 2)
        self.progress.itemconfigure(self.progress_item, start=(phase * -290) % 360,
                                    extent=110 if self.busy else 359)
        self.animation_job = self.root.after(40, self.animate)

    def select_filter(self, category):
        self.filter = category
        for panel in (self.hero_panel, self.home_news, self.library, self.news_page, self.history_page):
            panel.pack_forget()
        if category == "news":
            self.news_page.pack(fill="x")
        elif category == "history":
            self.history_page.pack(fill="x")
            self.render_history_rows()
        else:
            if category == "all":
                self.hero_panel.pack(fill="x")
                self.home_news.pack(fill="x", pady=(17, 0))
            self.library.pack(fill="x")
        self.update_navigation()
        self.render_library()
        self.viewport.yview_moveto(0)

    def scroll_library(self, event):
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget == self.viewport:
                self.viewport.yview_scroll(-int(event.delta / 120) * 3, "units")
                return "break"
            widget = widget.master

    def resize_library(self, window_id, width):
        self.viewport.itemconfigure(window_id, width=width)
        columns = 3 if width >= 730 else 2
        if columns != self.columns:
            self.columns = columns
            self.render_library()

    def update_navigation(self):
        for category, button in self.nav.items():
            selected = self.filter == category
            button.normal_bg = self.palette.nav_selected if selected else self.palette.nav
            button.configure(bg=button.normal_bg, highlightbackground=button.normal_bg,
                             fg=self.palette.accent if selected else self.palette.text)

    def render_library(self):
        for child in self.cards.winfo_children():
            child.destroy()
        self.app_labels.clear()
        self.launch_buttons.clear()
        self.app_tiles.clear()
        for column in range(3):
            self.cards.columnconfigure(column, weight=int(column < self.columns), uniform="card")
        if self.filter in ("news", "history"):
            return
        heading = "Библиотека" if self.filter == "all" else next(
            title for key, title, _ in self.filters if key == self.filter)
        self.section_title.config(text=heading)
        query = self.search.get().strip().casefold()
        names = (*APP_DETAILS, *self.guard.custom_apps)
        names = [name for name in names if
                 (self.filter == "all" or app_details(name)[4] == self.filter)
                 and query in app_details(name)[0].casefold()]
        self.count.config(text=str(len(names)))
        if not names:
            message = "По этому запросу ничего нет." if query else "Добавь приложение кнопкой «Добавить»."
            self.label(self.cards, message, bg=self.palette.bg, color=self.palette.muted, pady=16).grid(sticky="w", columnspan=self.columns)
        for index, name in enumerate(names):
            self.build_card(name, *divmod(index, self.columns))
        self.refresh_cards()

    def display_app_name(self, name):
        return app_details(name)[0]

    def build_card(self, name, row, column):
        title, description, color, symbol, _ = app_details(name)
        tile = tk.Frame(self.cards, bg=self.palette.panel, highlightbackground=self.palette.edge, highlightthickness=1)
        tile.grid(row=row, column=column, sticky="nsew",
                  padx=(0, 10 if column < self.columns - 1 else 0), pady=(0, 10))
        cover = tk.Canvas(tile, bg=self.palette.panel, height=100, width=1, bd=0, highlightthickness=0)
        cover.pack(fill="x")
        key = (color, symbol)
        if key not in self.images:
            self.images[key] = ImageTk.PhotoImage(card_art(*key, self.palette.is_light), master=self.root)
        cover.create_image(0, 0, anchor="nw", image=self.images[key])
        badge_bg = "#d9f7ea" if self.palette.is_light else "#18392f"
        badge = self.label(cover, "●  Работает", 9, color=self.palette.good, bg=badge_bg,
                           weight="bold", padx=7, pady=3)
        body = tk.Frame(tile, bg=self.palette.panel, padx=11, pady=8)
        body.pack(fill="both", expand=True)
        self.label(body, title, 12, weight="bold", wraplength=178, justify="left").pack(fill="x")
        self.label(body, description, 9, color=self.palette.muted, wraplength=175, justify="left").pack(fill="x", pady=(2, 6))
        stats_line = tk.Frame(body, bg=self.palette.panel)
        stats_line.pack(fill="x", pady=(0, 5))
        summary = self.label(stats_line, size=9, color=self.palette.muted)
        summary.pack(side="left", fill="x", expand=True)
        details = self.button(stats_line, "Статистика", lambda: self.open_app_activity(name, title), compact=True)
        details.config(padx=6, pady=2)
        details.pack(side="right")
        foot = tk.Frame(body, bg=self.palette.panel)
        foot.pack(fill="x", side="bottom")
        status = self.label(foot, size=8, color=self.palette.muted, wraplength=93, justify="left")
        status.pack(side="left", fill="x", expand=True)
        button = self.button(foot, "Запуск  ›", lambda: self.start_app(name), compact=True)
        button.configure(padx=7)
        button.pack(side="right")
        self.app_labels[name] = status
        self.launch_buttons[name] = button
        self.app_tiles[name] = (tile, badge, summary)
        for widget in (tile, cover, status, button, *body.winfo_children()):
            widget.bind("<Enter>", lambda _event: self.outline_app_tile(name, color), add="+")
            widget.bind("<Leave>", lambda _event: self.outline_app_tile(name, self.palette.edge), add="+")

    def outline_app_tile(self, name, color):
        tile, _, _ = self.app_tiles[name]
        active = bool((self.running or {}).get(name))
        tile.config(highlightbackground=self.palette.good if active else color)

    def open_add_app(self):
        if self.busy or self.settings_window is not None:
            return
        dialog = tk.Toplevel(self.root)
        self.settings_window = dialog
        dialog.title("Добавить приложение")
        dialog.configure(bg=self.palette.panel, padx=22, pady=19)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        name, path = tk.StringVar(dialog), tk.StringVar(dialog)
        console = tk.BooleanVar(dialog)
        self.label(dialog, "Название", 11, weight="bold").pack(fill="x")
        title = self.field(dialog, name)
        title.pack(fill="x", pady=(4, 11), ipady=4)
        self.label(dialog, "Исполняемый файл Windows", 11, weight="bold").pack(fill="x")
        row = tk.Frame(dialog, bg=self.palette.panel)
        row.pack(fill="x", pady=(4, 9))
        entry = self.field(row, path)
        entry.configure(width=39)
        entry.pack(side="left", fill="x", expand=True, ipady=4)

        def browse():
            filename = filedialog.askopenfilename(parent=dialog, title="Выбрать приложение",
                                                   filetypes=[("Приложения Windows", "*.exe")])
            if filename:
                path.set(filename)
                if not name.get().strip():
                    name.set(Path(filename).stem)

        self.button(row, "Обзор…", browse, compact=True).pack(side="right", padx=(7, 0))
        self.checkbox(dialog, "Открывать в отдельной консоли", console).pack(fill="x")
        error = self.label(dialog, color=self.palette.amber, wraplength=390, justify="left")
        error.pack(fill="x")

        def close():
            self.settings_window = None
            dialog.destroy()

        def save():
            try:
                app = CustomApp(name.get(), Path(path.get().strip()), console.get())
                if not app.path.is_file():
                    raise CatalogError("Файл не найден. Выбери существующий .exe.")
                self.guard.add_app(app)
            except (OSError, CatalogError) as problem:
                error.config(text=str(problem))
                return
            close()
            self.search.set("")
            self.select_filter("custom")
            self.refresh_process_snapshot()
            self.show_message(f"{app.name} добавлено в библиотеку.")

        buttons = tk.Frame(dialog, bg=self.palette.panel)
        buttons.pack(anchor="e", pady=(9, 0))
        self.button(buttons, "Отмена", close).pack(side="left", padx=(0, 8))
        self.button(buttons, "Добавить", save, primary=True).pack(side="left")
        dialog.protocol("WM_DELETE_WINDOW", close)
        dialog.bind("<Escape>", lambda _event: close())
        dialog.bind("<Return>", lambda _event: save())
        dialog.wait_visibility()
        dialog.grab_set()
        title.focus_set()

    def checkbox(self, parent, title, value, command=None):
        return tk.Checkbutton(parent, text=title, variable=value, command=command, bg=self.palette.panel, fg=self.palette.text,
                              activebackground=self.palette.panel, activeforeground=self.palette.accent, selectcolor=self.palette.bg,
                              font=(FONT, 10), anchor="w")
