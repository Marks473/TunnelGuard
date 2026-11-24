from dataclasses import asdict, dataclass, replace
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
import unicodedata
from xml.etree import ElementTree

from guard import GuardDenied
from settings import write_local_json
from windows_probe import current_route, probe_windows, resolve_through_tunnel, tunneled_get


NEWS_HOST = "news.google.com"
MAX_FEED_BYTES = 768 * 1024
MAX_CACHE_BYTES = 512 * 1024
ITEMS_PER_TOPIC = 24
FRESH_SECONDS = 60 * 60
RETRY_SECONDS = 15 * 60
MANUAL_SECONDS = 2 * 60

TOPICS = {
    "labs": ("OpenAI и Anthropic", '(OpenAI OR Anthropic OR "Claude Code") (release OR launch OR model OR announced) when:14d'),
    "china": ("ИИ из Китая", '(DeepSeek OR Qwen OR Moonshot OR MiniMax OR Zhipu OR Kimi) (AI OR model OR release) when:14d'),
    "agents": ("Агенты и CLI", '(OpenCode OR "Codex CLI" OR "agent harness" OR "coding agent") (AI OR LLM OR release) when:14d'),
    "orca": ("Orca и гайды", '"Orca" ("AI coding" OR worktree OR "coding agent" OR "Claude Code" OR "agent orchestration") (guide OR tutorial OR release OR update OR launch) -OrcaRouter -whale when:180d'),
    "models": ("Другие модели", '(Gemini OR Mistral OR Llama OR Gemma OR Cohere OR Grok) (AI OR model) (release OR launch OR announced) when:14d'),
}


@dataclass(frozen=True)
class Article:
    topic: str
    title: str
    source: str
    published: int
    russian_title: str = ""

    def display_title(self, *, original=False):
        return self.title if original else self.russian_title or self.title


@dataclass(frozen=True)
class NewsCache:
    fetched_at: int = 0
    articles: tuple[Article, ...] = ()


def news_path():
    return Path(os.environ["LOCALAPPDATA"]) / "TunnelGuard" / "news.json"


def clean_text(value, limit):
    value = "".join(letter for letter in value if letter.isspace() or not unicodedata.category(letter).startswith("C"))
    return " ".join(value.split())[:limit]


def read_rss(body, topic, now):
    text = body.decode("utf-8-sig")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("RSS содержит неподдерживаемые объявления XML.")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValueError("Агрегатор вернул некорректный RSS.") from error
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise ValueError("Агрегатор вернул неизвестный формат ленты.")
    articles = []
    for item in channel.findall("item")[:120]:
        source = clean_text(item.findtext("source", ""), 72)
        title = clean_text(item.findtext("title", ""), 340)
        if source:
            title = title.removesuffix(" - " + source)
        title = title[:250]
        if topic == "orca":
            if not re.search(r"\borca\b", title, re.IGNORECASE) or not re.search(
                r"\b(codex|code|coding|agents?|worktrees?|terminal|opencode|orchestrat\w*)\b", title, re.IGNORECASE
            ):
                continue
        try:
            date = parsedate_to_datetime(item.findtext("pubDate", ""))
            if date.tzinfo is None:
                continue
            published = int(date.timestamp())
        except (ValueError, OverflowError, OSError):
            continue
        if title and source and 0 < published <= now + 600:
            articles.append(Article(topic, title, source, published))
    return sorted(articles, key=lambda item: item.published, reverse=True)[:ITEMS_PER_TOPIC]


def fetch_news(target_ip):
    evidence, _errors = probe_windows(target_ip)
    if not evidence.confirmed:
        raise GuardDenied("Лента ждёт подтверждения IPv4 двумя сервисами.")
    route = evidence.route_after
    if current_route() != route:
        raise GuardDenied("Маршрут VPN изменился до обновления ленты.")
    remote_ip = resolve_through_tunnel(NEWS_HOST, route)
    now = int(time.time())
    articles = []
    for topic, (_, query) in TOPICS.items():
        query_string = urlencode({"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
        body = tunneled_get(NEWS_HOST, remote_ip, route, "/rss/search?" + query_string,
                            accept="application/rss+xml, application/xml", max_bytes=MAX_FEED_BYTES)
        articles.extend(read_rss(body, topic, now))
    if current_route() != route:
        raise GuardDenied("Маршрут VPN изменился во время обновления ленты.")
    unique = {}
    for article in sorted(articles, key=lambda item: item.published, reverse=True):
        unique.setdefault(article.title.casefold(), article)
    if not unique:
        raise ValueError("Агрегатор не вернул заголовки.")
    return NewsCache(now, tuple(unique.values()))


def load_news(path=None):
    path = path if path is not None else news_path()
    try:
        with path.open("rb") as file:
            body = file.read(MAX_CACHE_BYTES + 1)
        if len(body) > MAX_CACHE_BYTES:
            return NewsCache()
        data = json.loads(body.decode("utf-8"))
        items, fetched_at = data["articles"], data["fetched_at"]
        if (type(fetched_at) is not int or not 0 < fetched_at <= int(time.time()) + 600
                or not isinstance(items, list) or len(items) > ITEMS_PER_TOPIC * len(TOPICS)):
            return NewsCache()
        articles = []
        for item in items:
            topic, published = item["topic"], item["published"]
            title, source = clean_text(item["title"], 250), clean_text(item["source"], 72)
            if topic in TOPICS and title and source and type(published) is int and 0 < published <= fetched_at + 600:
                russian = item.get("russian_title", "")
                translation = clean_text(russian, 360) if isinstance(russian, str) else ""
                articles.append(Article(topic, title, source, published, translation))
        return NewsCache(fetched_at, tuple(sorted(articles, key=lambda item: item.published, reverse=True)))
    except (OSError, ValueError, TypeError, KeyError):
        return NewsCache()


def with_translations(cache, translations):
    articles = tuple(
        replace(item, russian_title=clean_text(translations.get(item.title, ""), 360))
        if not item.russian_title and translations.get(item.title) else item
        for item in cache.articles
    )
    return cache if articles == cache.articles else NewsCache(cache.fetched_at, articles)


def save_news(cache, path=None):
    path = path if path is not None else news_path()
    write_local_json(path, {
        "fetched_at": cache.fetched_at,
        "articles": [asdict(item) for item in cache.articles],
    })
