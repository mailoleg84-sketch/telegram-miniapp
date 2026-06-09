"""Тесты выбора бесплатной картинки слова: фото только для конкретных типов,
проброс топика, маппинг топик->Pixabay-категория."""
import unittest
from unittest.mock import patch

from webapp import server
from webapp.free_images import _TOPIC_CATEGORY, fetch_word_illustration
import asyncio


SVG = "/vocabulary-visual.svg?w=x&v=object"


class VocabCardImageUrlTests(unittest.TestCase):
    def setUp(self):
        # Делаем поведение детерминированным независимо от .env.
        self._p = patch("webapp.server.VOCAB_FREE_PHOTOS", True)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_concrete_object_gets_photo_with_topic(self):
        url = server._vocab_card_image_url("table", SVG, emoji="", visual_type="object", topic="home")
        self.assertTrue(url.startswith("/vocabulary-photo?"))
        self.assertIn("w=table", url)
        self.assertIn("t=home", url)

    def test_action_gets_photo(self):
        url = server._vocab_card_image_url("travel", SVG, emoji="", visual_type="action", topic="travel")
        self.assertTrue(url.startswith("/vocabulary-photo?"))

    def test_abstract_situation_falls_back_to_svg(self):
        url = server._vocab_card_image_url("reason", SVG, emoji="", visual_type="situation", topic="abstract")
        self.assertEqual(url, SVG)

    def test_grammar_type_falls_back_to_svg(self):
        url = server._vocab_card_image_url("because", SVG, emoji="", visual_type="cause_effect", topic="grammar")
        self.assertEqual(url, SVG)

    def test_emoji_word_keeps_svg_fallback(self):
        # Слово с эмодзи рисуется глифом на клиенте -> фото не тянем.
        url = server._vocab_card_image_url("apple", SVG, emoji="🍎", visual_type="object", topic="food")
        self.assertEqual(url, SVG)

    def test_sensitive_word_never_fetches_photo(self):
        url = server._vocab_card_image_url("knife", SVG, emoji="", visual_type="object", topic="home")
        self.assertEqual(url, SVG)

    def test_photos_disabled_falls_back(self):
        with patch("webapp.server.VOCAB_FREE_PHOTOS", False):
            url = server._vocab_card_image_url("table", SVG, emoji="", visual_type="object", topic="home")
        self.assertEqual(url, SVG)


class TopicCategoryTests(unittest.TestCase):
    def test_known_topics_map_to_pixabay_categories(self):
        self.assertEqual(_TOPIC_CATEGORY["animals"], "animals")
        self.assertEqual(_TOPIC_CATEGORY["transport"], "transportation")
        self.assertEqual(_TOPIC_CATEGORY["family"], "people")
        self.assertEqual(_TOPIC_CATEGORY["clothes"], "fashion")

    def test_unknown_topic_has_no_category(self):
        self.assertNotIn("toys", _TOPIC_CATEGORY)
        self.assertNotIn("", _TOPIC_CATEGORY)

    def test_fetch_returns_none_without_api_key(self):
        # Без ключа сеть не дёргается (детерминированно).
        with patch("webapp.free_images.PIXABAY_API_KEY", ""):
            result = asyncio.run(fetch_word_illustration("table", "home"))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
