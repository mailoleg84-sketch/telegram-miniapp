"""Тесты выбора бесплатной картинки слова: фото только для конкретных типов,
проброс топика, маппинг топик->Pixabay-категория."""
import unittest
from unittest.mock import patch, AsyncMock
from types import SimpleNamespace

from aiohttp import web

from webapp import server
from webapp.free_images import _TOPIC_CATEGORY, fetch_word_illustration
from webapp.vocabulary_visualizer import determine_visual_type, determine_part_of_speech
import asyncio


SVG = "/vocabulary-visual.svg?w=x&v=object"


class VocabCardImageUrlTests(unittest.TestCase):
    """Карточки слов больше НЕ используют фотосток: _vocab_card_image_url всегда
    возвращает контролируемый SVG/AI fallback — для любого слова и независимо от эмодзи."""

    def test_card_image_is_never_a_photo(self):
        cases = [
            ("table", "", "object", "home"),        # бывший «можно фото» — теперь SVG
            ("apple", "🍎", "object", "food"),       # эмодзи-слово — основная картинка SVG
            ("visited", "", "action", "travel"),
            ("lesson", "", "situation", "school"),
            ("answer", "", "situation", "school"),
            ("because", "", "cause_effect", "grammar"),
            ("the", "", "no_good_visual", "basic"),
            ("knife", "", "object", "home"),
        ]
        for word, emoji, vt, topic in cases:
            with self.subTest(word=word):
                url = server._vocab_card_image_url(word, SVG, emoji=emoji, visual_type=vt, topic=topic)
                self.assertEqual(url, SVG)
                self.assertNotIn("/vocabulary-photo", url)

    def test_scene_words_stay_situation_not_object(self):
        # lesson/class остаются учебной ситуацией (не object) — основа единой сцены.
        for w in ("lesson", "class"):
            self.assertEqual(determine_visual_type(w, determine_part_of_speech(w), "school"), "situation")


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


class _FakeResp:
    def __init__(self, status=200, payload=None, body=b""):
        self.status = status
        self._payload = payload or {}
        self._body = body
        self.headers = {"Content-Type": "image/jpeg", "Content-Length": str(len(body) or 1000)}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload

    async def read(self):
        return self._body


class _FakeSession:
    """Имитация aiohttp-сессии: API-вызовы отдают заранее заданные payload'ы по
    очереди, запрос картинки — валидный jpeg."""
    def __init__(self, api_payloads, image_body):
        self.api_payloads = list(api_payloads)
        self.image_body = image_body
        self.api_calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, **kw):
        if "pixabay.com/api" in url:
            payload = self.api_payloads[self.api_calls] if self.api_calls < len(self.api_payloads) else {"hits": []}
            self.api_calls += 1
            return _FakeResp(200, payload)
        return _FakeResp(200, body=self.image_body)


class PixabayFallbackTests(unittest.TestCase):
    def test_falls_back_to_no_category_when_category_empty(self):
        import webapp.free_images as fi
        # Первые два варианта (с категорией) пустые, третий (без категории) — хит.
        hit = {"hits": [{"webformatURL": "https://pixabay.com/get/photo.jpg"}]}
        fake = _FakeSession([{"hits": []}, {"hits": []}, hit], b"\xff\xd8\xff" + b"x" * 500)
        with patch("webapp.free_images.PIXABAY_API_KEY", "fake-key"), \
             patch("webapp.free_images.aiohttp.ClientSession", return_value=fake):
            result = asyncio.run(fi.fetch_word_illustration("table", "home"))  # home->buildings
        self.assertIsNotNone(result)
        self.assertEqual(result[1], "image/jpeg")
        # Дошли до 3-го запроса => fallback без категории сработал.
        self.assertEqual(fake.api_calls, 3)


class StopwordClassificationTests(unittest.TestCase):
    """Служебные/сравнительные/временные слова не должны быть object (→ нет фото),
    но настоящие '-er'-существительные обязаны остаться object."""

    def test_function_and_comparative_words_are_no_good_visual(self):
        for w in ("for", "or", "her", "better", "faster", "lower", "today", "december"):
            with self.subTest(word=w):
                self.assertEqual(determine_visual_type(w, determine_part_of_speech(w)), "no_good_visual")

    def test_real_er_nouns_stay_object(self):
        for w in ("paper", "door", "letter", "monster", "shower", "flower", "silver"):
            with self.subTest(word=w):
                self.assertEqual(determine_visual_type(w, determine_part_of_speech(w)), "object")


class VocabularyPhotoHandlerTests(unittest.TestCase):
    """Публичный /vocabulary-photo не тянет Pixabay для слов вне PHOTO_SAFE_OBJECTS:
    даже при включённом фотостоке возвращает SVG-редирект (запрет на уровне роута,
    не только в payload)."""

    @staticmethod
    def _request(w, t=""):
        return SimpleNamespace(query={"w": w, "t": t}, remote="127.0.0.1")

    def test_disallowed_words_redirect_to_svg_without_pixabay(self):
        no_pixabay = AsyncMock(side_effect=AssertionError("Pixabay must not be called"))
        for word in ("lesson", "answer", "visited", "because", "the"):
            with self.subTest(word=word):
                with patch("webapp.server.VOCAB_FREE_PHOTOS", True), \
                     patch("webapp.server.fetch_word_illustration", new=no_pixabay):
                    resp = asyncio.run(server.vocabulary_photo_handler(self._request(word)))
                self.assertIsInstance(resp, web.HTTPFound)
                self.assertIn("/vocabulary-visual.svg", resp.location)


class UnifiedCardImageTests(unittest.TestCase):
    """Единый визуальный язык: основная картинка карточки (_word_dict) — SVG-сцена для
    ВСЕХ слов (вкл. apple/cat/dog), никогда не фотосток; эмодзи остаётся как бейдж."""

    @staticmethod
    def _row(word, translation, topic, example=""):
        return {"id": 1, "word": word, "translation": translation, "transcription": "",
                "example": example, "topic": topic, "age_group": "8_10"}

    def test_all_words_card_image_is_svg_scene_not_photo(self):
        cases = [("apple", "яблоко", "food"), ("cat", "кошка", "animals"),
                 ("dog", "собака", "animals"), ("car", "машина", "transport"),
                 ("book", "книга", "reading"), ("lesson", "урок", "school"),
                 ("answer", "ответ", "school"), ("visited", "посетил", "travel"),
                 ("because", "потому что", "grammar")]
        for word, tr, topic in cases:
            with self.subTest(word=word):
                d = server._word_dict(self._row(word, tr, topic))
                self.assertTrue(d["image_url"].startswith("/vocabulary-visual.svg"),
                                f"{word}: {d['image_url']}")
                self.assertNotIn("/vocabulary-photo", d["image_url"])

    def test_emoji_word_keeps_svg_image_and_emoji_badge(self):
        # apple: основная картинка — SVG-сцена, а эмодзи остаётся в payload (бейдж).
        d = server._word_dict(self._row("apple", "яблоко", "food"))
        self.assertTrue(d["image_url"].startswith("/vocabulary-visual.svg"))
        self.assertTrue(d["emoji"], "эмодзи остаётся как декоративный бейдж")


if __name__ == "__main__":
    unittest.main()
