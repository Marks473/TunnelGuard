from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from news_feed import Article, NewsCache, load_news, save_news, with_translations
from news_translation import translate_titles


class TranslationTests(unittest.TestCase):
    def test_legacy_news_cache_loads_and_preserves_english_when_translation_is_added(self):
        now = int(time.time())
        original = "New model is available"
        with TemporaryDirectory() as folder:
            path = Path(folder) / "news.json"
            path.write_text(
                '{"fetched_at": %d, "articles": [{"topic": "models", "title": "%s", '
                '"source": "Independent News", "published": %d}]}' % (now, original, now - 30),
                encoding="utf-8",
            )
            legacy = load_news(path)
            self.assertEqual(legacy.articles[0].display_title(), original)
            translated = with_translations(legacy, {original: "Новая модель доступна"})
            save_news(translated, path)
            updated = load_news(path)
        self.assertEqual(updated.fetched_at, legacy.fetched_at)
        self.assertEqual(updated.articles[0].source, legacy.articles[0].source)
        self.assertEqual(updated.articles[0].display_title(), "Новая модель доступна")
        self.assertEqual(updated.articles[0].display_title(original=True), original)

    def test_existing_translations_are_preserved(self):
        cache = NewsCache(1, (Article("orca", "Orca adds worktrees", "Journal", 1, "Orca добавляет рабочие деревья"),))
        self.assertIs(with_translations(cache, {"Orca adds worktrees": "Другая версия перевода"}), cache)

    def test_russian_titles_do_not_load_model(self):
        with patch("news_translation.load_translator") as translator:
            self.assertEqual(translate_titles(("Новая модель от OpenAI",)), {
                "Новая модель от OpenAI": "Новая модель от OpenAI",
            })
        translator.assert_not_called()

    def test_model_receives_unique_english_titles_and_keeps_cyrillic_output(self):
        processor = Mock()
        processor.encode.return_value = [["new", "model"], ["GPT"]]
        processor.decode.side_effect = ["Новая модель", "GPT"]
        engine = Mock()
        engine.translate_batch.return_value = [Mock(hypotheses=[["ru"]]), Mock(hypotheses=[["GPT"]])]
        with patch("news_translation.load_translator", return_value=(processor, processor, engine)):
            result = translate_titles(("new model", "GPT", "new model"))
        processor.encode.assert_called_once_with(["new model", "GPT"], out_type=str)
        self.assertEqual(result, {"new model": "Новая модель"})
