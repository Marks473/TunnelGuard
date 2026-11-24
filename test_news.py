import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from guard import Evidence, GuardDenied
from news_feed import Article, NewsCache, TOPICS, fetch_news, load_news, read_rss, save_news
from windows_probe import Route, TunneledHttps, resolve_through_tunnel, tunneled_get


ROUTE = Route("test", 2, "10.0.0.2")
TARGET = "203.0.113.42"
XML = b"""<rss><channel><item>
<title>Orca adds coding worktrees - Independent News</title><source url="https://publisher.invalid">Independent News</source>
<link>https://publisher.invalid/item</link><description><![CDATA[<img src="https://publisher.invalid/a">]]></description>
<pubDate>Sat, 18 Oct 2025 10:00:00 GMT</pubDate>
</item></channel></rss>"""


class NewsTests(unittest.TestCase):
    def test_offline_news_does_not_resolve_or_contact_aggregator(self):
        with patch("windows_probe.current_route", return_value=None), \
             patch("windows_probe.tunneled_get") as probe_request, \
             patch("news_feed.tunneled_get") as rss_request:
            with self.assertRaises(GuardDenied):
                fetch_news(TARGET)
            probe_request.assert_not_called()
            rss_request.assert_not_called()

    def test_unconfirmed_ip_or_changed_route_stops_before_aggregator_dns(self):
        good = Evidence(ROUTE, ROUTE, (TARGET, TARGET), TARGET)
        bad = Evidence(ROUTE, ROUTE, (TARGET, "192.0.2.1"), TARGET)
        for evidence, route in ((bad, ROUTE), (good, None)):
            with self.subTest(evidence=evidence, route=route), \
                 patch("news_feed.probe_windows", return_value=(evidence, [])), \
                 patch("news_feed.current_route", return_value=route), \
                 patch("news_feed.resolve_through_tunnel") as resolve, \
                 patch("news_feed.tunneled_get") as request:
                with self.assertRaises(GuardDenied):
                    fetch_news(TARGET)
                resolve.assert_not_called()
                request.assert_not_called()

    def test_feed_contacts_only_allowed_rss_paths_and_ignores_every_embedded_url(self):
        evidence = Evidence(ROUTE, ROUTE, (TARGET, TARGET), TARGET)
        with patch("news_feed.probe_windows", return_value=(evidence, [])), \
             patch("news_feed.current_route", return_value=ROUTE), \
             patch("news_feed.resolve_through_tunnel", return_value="8.8.8.8") as resolve, \
             patch("news_feed.tunneled_get", return_value=XML) as request:
            result = fetch_news(TARGET)
        resolve.assert_called_once_with("news.google.com", ROUTE)
        self.assertEqual(len(request.call_args_list), len(TOPICS))
        for call in request.call_args_list:
            host, ip, route, path = call.args
            self.assertEqual((host, ip, route), ("news.google.com", "8.8.8.8", ROUTE))
            parsed = urlsplit(path)
            self.assertEqual(parsed.path, "/rss/search")
            self.assertIn("q", parse_qs(parsed.query))
        self.assertEqual(len(result.articles), 1)
        self.assertEqual(result.articles[0].title, "Orca adds coding worktrees")
        self.assertEqual(result.articles[0].source, "Independent News")
        self.assertNotIn("publisher.invalid", repr(result))

    def test_xml_dtd_is_rejected_and_orca_unrelated_titles_are_excluded(self):
        with self.assertRaises(ValueError):
            read_rss(b'<!DOCTYPE foo [<!ENTITY evil SYSTEM "https://publisher.invalid">]><rss>&evil;</rss>',
                     "orca", int(time.time()))
        irrelevant = XML.replace(b"Orca adds coding worktrees", b"Orca whales return to the harbor")
        self.assertEqual(read_rss(irrelevant, "orca", int(time.time())), [])
        self.assertEqual(len(read_rss(XML, "orca", int(time.time()))), 1)

    def test_cache_survives_reload_and_invalid_cache_returns_empty(self):
        now = int(time.time())
        cache = NewsCache(now, (Article("china", "Новая модель", "Издание", now - 10),))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "nested" / "news.json"
            self.assertEqual(load_news(path), NewsCache())
            save_news(cache, path)
            self.assertEqual(load_news(path), cache)
            path.write_text('{"articles": {}}', encoding="utf-8")
            self.assertEqual(load_news(path), NewsCache())


class NetworkBoundaryTests(unittest.TestCase):
    def test_wrong_egress_does_not_create_socket(self):
        connection = TunneledHttps("news.google.com", "8.8.8.8", ROUTE)
        with patch("windows_probe.current_route", return_value=ROUTE), \
             patch("windows_probe.best_interface", return_value=9), \
             patch("windows_probe.socket.socket") as socket:
            with self.assertRaises(GuardDenied):
                connection.connect()
            socket.assert_not_called()

    def test_changed_route_after_tls_stops_before_http(self):
        with patch("windows_probe.TunneledHttps") as https, \
             patch("windows_probe.current_route", return_value=None):
            with self.assertRaises(GuardDenied):
                tunneled_get("news.google.com", "8.8.8.8", ROUTE, "/rss/search",
                             accept="application/xml", max_bytes=1000)
        https.return_value.request.assert_not_called()
        https.return_value.close.assert_called_once()

    def test_redirect_is_rejected_without_contacting_redirect_target(self):
        with patch("windows_probe.TunneledHttps") as https, \
             patch("windows_probe.current_route", return_value=ROUTE):
            response = https.return_value.getresponse.return_value.__enter__.return_value
            response.status = 302
            response.getheader.return_value = "https://publisher.invalid/"
            with self.assertRaises(GuardDenied):
                tunneled_get("news.google.com", "8.8.8.8", ROUTE, "/rss/search",
                             accept="application/xml", max_bytes=1000)
        self.assertEqual(https.call_count, 1)
        self.assertEqual(https.return_value.request.call_count, 1)
        response.read.assert_not_called()

    def test_resolution_uses_only_bound_doh_and_rejects_private_addresses(self):
        with patch("windows_probe.socket.getaddrinfo") as system_dns, \
             patch("windows_probe.tunneled_get", return_value=b'{"Status":0,"Answer":[{"type":1,"data":"192.168.0.1"}]}') as get:
            with self.assertRaises(GuardDenied):
                resolve_through_tunnel("news.google.com", ROUTE)
            self.assertEqual(get.call_args.args[:3], ("cloudflare-dns.com", "1.1.1.1", ROUTE))
            self.assertEqual(parse_qs(urlsplit(get.call_args.args[3]).query),
                             {"name": ["news.google.com"], "type": ["A"]})
            system_dns.assert_not_called()
