from datetime import datetime
import tkinter as tk
from textwrap import shorten

from news_feed import TOPICS


class NewsView:
    def build_news(self, page):
        p = self.palette
        self.home_news = tk.Frame(page, bg=p.bg)
        home_header = tk.Frame(self.home_news, bg=p.bg)
        home_header.pack(fill="x", pady=(0, 8))
        self.label(home_header, "Главные новости ИИ", 16, bg=p.bg, weight="bold").pack(side="left")
        self.button(home_header, "К ленте  ›", lambda: self.select_filter("news"), compact=True).pack(side="right")
        self.headlines = tk.Frame(self.home_news, bg=p.bg)
        self.headlines.pack(fill="x")
        for column in range(3):
            self.headlines.columnconfigure(column, weight=1, uniform="headlines")

        self.news_page = tk.Frame(page, bg=p.bg)
        header = tk.Frame(self.news_page, bg=p.hero, padx=18, pady=14,
                          highlightthickness=1, highlightbackground=p.hero_edge)
        header.pack(fill="x", pady=(0, 13))
        self.news_refresh_button = self.button(header, "Обновить", self.refresh_news, primary=True)
        self.news_refresh_button.pack(side="right", padx=(8, 0))
        self.news_language_button = self.button(header, "", self.toggle_news_language)
        self.news_language_button.pack(side="right")
        intro = tk.Frame(header, bg=p.hero)
        intro.pack(side="left", fill="x", expand=True)
        self.label(intro, "Новости ИИ", 22, bg=p.hero, weight="bold").pack(fill="x")
        self.news_status = self.label(intro, size=9, bg=p.hero, color=p.hero_text,
                                      wraplength=440, justify="left")
        self.news_status.pack(fill="x", pady=(3, 0))
        self.news_topics = tk.Frame(self.news_page, bg=p.bg)
        self.news_topics.pack(fill="x", pady=(0, 8))
        self.topic_buttons = {}
        for key, title in (("all", "Все"), *((key, values[0]) for key, values in TOPICS.items())):
            option = self.button(self.news_topics, title, lambda selected=key: self.select_news_topic(selected),
                                 compact=True)
            option.grid(row=0, column=len(self.topic_buttons), ipadx=0, padx=(0, 4), sticky="w")
            option.config(padx=6)
            self.topic_buttons[key] = option
        self.news_meta = self.label(self.news_page, size=9, bg=p.bg, color=p.muted, pady=5)
        self.news_meta.pack(fill="x")
        self.news_rows = tk.Frame(self.news_page, bg=p.bg)
        self.news_rows.pack(fill="x")
        self.news_empty_home = self.news_empty_rows = None
        self.render_news()

    def render_news(self):
        self.render_news_status()
        self.render_headlines()
        self.render_news_rows()

    def render_news_status(self):
        p = self.palette
        status = self.news_update_status()
        self.news_status.config(text=status, fg=p.hero_text)
        for label in (self.news_empty_home, self.news_empty_rows):
            if label is not None:
                label.config(text=status)
        if self.news_cache.fetched_at:
            updated = datetime.fromtimestamp(self.news_cache.fetched_at).strftime("%d.%m в %H:%M")
            text = f"Google News RSS · обновлено {updated}"
        else:
            text = "Google News RSS"
        self.news_meta.config(text=text)
        self.set_button(self.news_refresh_button, self.can_refresh_news())
        self.news_language_button.config(text="По-русски" if self.news_original else "Оригинал")

    def render_headlines(self):
        for widget in self.headlines.winfo_children():
            widget.destroy()
        p = self.palette
        articles = self.news_cache.articles
        self.news_empty_home = None
        if not articles:
            self.news_empty_home = self.label(self.headlines, self.news_update_status(), 10, color=p.muted,
                                             bg=p.panel, padx=12, pady=11, justify="left", wraplength=525)
            self.news_empty_home.grid(row=0, column=0, columnspan=3, sticky="ew")
            return
        by_topic = {}
        for article in articles:
            by_topic.setdefault(article.topic, article)
        headlines = list(by_topic.values())[:3]
        if len(headlines) < 3:
            remaining = [article for article in articles if article not in headlines]
            headlines.extend(remaining[:3 - len(headlines)])
        for column, article in enumerate(headlines):
            tile = tk.Frame(self.headlines, bg=p.panel, padx=10, pady=8,
                            highlightthickness=1, highlightbackground=p.edge)
            tile.grid(row=0, column=column, sticky="nsew", padx=(0, 8 if column < 2 else 0))
            self.label(tile, TOPICS[article.topic][0], 9, color=p.accent, weight="bold").pack(fill="x")
            excerpt = shorten(article.display_title(), width=106, placeholder="…")
            self.label(tile, excerpt, 10, weight="bold", wraplength=168, justify="left").pack(fill="x", pady=3)
            self.label(tile, shorten(article.source, width=30, placeholder="…"), 8, color=p.muted).pack(
                side="bottom", fill="x")

    def toggle_news_language(self):
        self.news_original = not self.news_original
        self.render_news_status()
        self.render_news_rows()

    def select_news_topic(self, topic):
        self.news_topic = topic
        self.news_limit = 30
        self.render_news_rows()

    def expand_news(self):
        self.news_limit += 30
        self.render_news_rows()

    def render_news_rows(self):
        p = self.palette
        for topic, button in self.topic_buttons.items():
            selected = topic == self.news_topic
            button.normal_bg = p.nav_selected if selected else p.button
            button.config(bg=button.normal_bg, highlightbackground=button.normal_bg,
                          fg=p.accent if selected else p.text)
        for widget in self.news_rows.winfo_children():
            widget.destroy()
        items = [article for article in self.news_cache.articles
                 if self.news_topic == "all" or article.topic == self.news_topic]
        self.news_empty_rows = None
        if not items:
            has_news = bool(self.news_cache.articles)
            text = "В этой подборке пока нет заголовков." if has_news else self.news_update_status()
            label = self.label(self.news_rows, text, color=p.muted, bg=p.bg, pady=12, wraplength=525, justify="left")
            label.pack(fill="x")
            if not has_news:
                self.news_empty_rows = label
            return
        for article in items[:self.news_limit]:
            row = tk.Frame(self.news_rows, bg=p.panel, padx=12, pady=8,
                           highlightthickness=1, highlightbackground=p.edge)
            row.pack(fill="x", pady=(0, 6))
            date = datetime.fromtimestamp(article.published).strftime("%d.%m · %H:%M")
            self.label(row, date, 9, color=p.muted).pack(side="right", anchor="n", padx=(5, 0))
            summary = tk.Frame(row, bg=p.panel)
            summary.pack(side="left", fill="x", expand=True)
            title = self.label(summary, article.display_title(original=self.news_original), 11,
                               weight="bold", wraplength=440, justify="left")
            title.pack(fill="x")
            summary.bind("<Configure>", lambda event, label=title: label.config(wraplength=max(100, event.width - 3)))
            metadata = f"{TOPICS[article.topic][0]}  ·  {article.source}"
            self.label(summary, metadata, 9, color=p.muted, wraplength=413, justify="left").pack(fill="x", pady=(2, 0))
        if self.news_limit < len(items):
            self.button(self.news_rows, "Показать ещё", self.expand_news).pack(anchor="w", pady=5)
