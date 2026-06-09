"""Тесты общей выборки тренировочного слова (_select_training_word).

Проверяем все ветки каскада: запрошенное слово, ошибки payload/404, fallback на
практику, focus=review и признак review_empty, отсутствие слов (500).
"""
import unittest
from unittest.mock import AsyncMock, patch

from webapp.server import _select_training_word


_W = {"id": 5, "word": "cat", "translation": "кошка", "transcription": "", "topic": "animals"}


class SelectTrainingWordTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_word_returned(self):
        with patch("database.get_word_by_id", AsyncMock(return_value=_W)):
            word, error, focus, review_empty = await _select_training_word(1, {"word_id": 5}, "8_10")
        self.assertIsNone(error)
        self.assertEqual(word["id"], 5)
        self.assertEqual(focus, "all")
        self.assertFalse(review_empty)

    async def test_requested_word_bad_payload(self):
        word, error, _focus, _re = await _select_training_word(1, {"word_id": "abc"}, "8_10")
        self.assertIsNone(word)
        self.assertEqual(error.status, 400)

    async def test_requested_word_not_found(self):
        with patch("database.get_word_by_id", AsyncMock(return_value=None)):
            word, error, _focus, _re = await _select_training_word(1, {"word_id": 99}, "8_10")
        self.assertIsNone(word)
        self.assertEqual(error.status, 404)

    async def test_practice_fallback(self):
        with patch("database.get_review_word", AsyncMock(return_value=None)), \
             patch("database.get_practice_word", AsyncMock(return_value=_W)):
            word, error, focus, review_empty = await _select_training_word(1, {}, "8_10")
        self.assertIsNone(error)
        self.assertEqual(word["id"], 5)
        self.assertEqual(focus, "all")
        self.assertFalse(review_empty)

    async def test_review_focus_found(self):
        with patch("database.get_review_word", AsyncMock(return_value=_W)), \
             patch("database.get_practice_word", AsyncMock(return_value=None)):
            word, error, focus, review_empty = await _select_training_word(1, {"focus": "review"}, "8_10")
        self.assertIsNone(error)
        self.assertEqual(focus, "review")
        self.assertFalse(review_empty)

    async def test_review_empty_then_practice(self):
        # focus=review, но review-слова нет -> review_empty True; практика находит слово.
        with patch("database.get_review_word", AsyncMock(return_value=None)), \
             patch("database.get_practice_word", AsyncMock(return_value=_W)):
            word, error, focus, review_empty = await _select_training_word(1, {"focus": "review"}, "8_10")
        self.assertIsNone(error)
        self.assertTrue(review_empty)
        self.assertEqual(word["id"], 5)

    async def test_no_words_returns_500(self):
        with patch("database.get_review_word", AsyncMock(return_value=None)), \
             patch("database.get_practice_word", AsyncMock(return_value=None)):
            word, error, _focus, _re = await _select_training_word(1, {}, "8_10")
        self.assertIsNone(word)
        self.assertEqual(error.status, 500)


if __name__ == "__main__":
    unittest.main()
