"""Юнит-тесты выборки дистракторов и построения вопросов квиза/игры.

После анти-N+1 рефакторинга билдеры берут дистракторы из готового пула и не
ходят в БД (БД мокаем как 'не должно вызываться'), что и проверяем.
"""
import unittest
from unittest.mock import AsyncMock, patch

from webapp.server import (
    _pick_distractors,
    _build_vocab_question,
    _build_word_hunt_round,
)


def _word(wid=1, word="apple", translation="яблоко"):
    return {
        "id": wid,
        "word": word,
        "translation": translation,
        "transcription": "ˈæpəl",
        "example": "I eat an apple every day.",
        "topic": "food",
    }


def _pool(n=10, start=2):
    return [
        {"id": i, "word": f"word{i}", "translation": f"перевод{i}"}
        for i in range(start, start + n)
    ]


class PickDistractorsTests(unittest.TestCase):
    def test_excludes_correct_and_returns_count(self):
        pool = _pool(10)
        picked = _pick_distractors(pool, correct_id=2, count=3)
        self.assertEqual(len(picked), 3)
        ids = [p["id"] for p in picked]
        self.assertNotIn(2, ids)
        self.assertEqual(len(set(ids)), 3, "дистракторы должны быть различны")

    def test_returns_all_when_pool_small(self):
        pool = _pool(2, start=5)  # ids 5,6
        picked = _pick_distractors(pool, correct_id=99, count=3)
        self.assertEqual(len(picked), 2)

    def test_empty_pool(self):
        self.assertEqual(_pick_distractors(None, 1, 3), [])
        self.assertEqual(_pick_distractors([], 1, 3), [])


class BuildVocabQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def test_translation_question_uses_pool_not_db(self):
        word = _word(1)
        pool = _pool(10)
        with patch("database.get_word_options", new=AsyncMock(side_effect=AssertionError)), \
             patch("database.get_random_words", new=AsyncMock(side_effect=AssertionError)):
            q = await _build_vocab_question(word, "8_10", index=0, pool=pool)
        self.assertEqual(q["type"], "translation")
        self.assertEqual(len(q["options"]), 4)
        # Ровно один вариант — правильный: его id == word_id, метка == перевод.
        correct = [o for o in q["options"] if o["id"] == 1]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]["label"], "яблоко")
        # Остальные три — дистракторы из пула.
        distractor_ids = [o["id"] for o in q["options"] if o["id"] != 1]
        self.assertEqual(len(distractor_ids), 3)
        self.assertTrue(set(distractor_ids).issubset({p["id"] for p in pool}))

    async def test_word_question_uses_word_labels(self):
        word = _word(1)
        pool = _pool(10)
        with patch("database.get_word_options", new=AsyncMock(side_effect=AssertionError)), \
             patch("database.get_random_words", new=AsyncMock(side_effect=AssertionError)):
            q = await _build_vocab_question(word, "8_10", index=1, pool=pool)
        self.assertEqual(len(q["options"]), 4)
        correct = [o for o in q["options"] if o["id"] == 1]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]["label"], "apple")

    async def test_falls_back_to_db_when_pool_empty(self):
        word = _word(1)
        fake = AsyncMock(return_value=[
            {"id": 7, "translation": "семь"},
            {"id": 8, "translation": "восемь"},
            {"id": 9, "translation": "девять"},
        ])
        with patch("database.get_word_options", new=fake):
            q = await _build_vocab_question(word, "8_10", index=0, pool=[])
        fake.assert_awaited_once()
        self.assertEqual(len(q["options"]), 4)


class BuildWordHuntRoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_uses_pool_not_db(self):
        word = _word(1)
        pool = _pool(10)
        with patch("database.get_random_words", new=AsyncMock(side_effect=AssertionError)):
            r = await _build_word_hunt_round(word, "8_10", pool=pool)
        self.assertEqual(len(r["options"]), 4)
        correct = [o for o in r["options"] if o["id"] == 1]
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]["word"], "apple")
        distractor_ids = [o["id"] for o in r["options"] if o["id"] != 1]
        self.assertEqual(len(set(distractor_ids)), 3)


def _img_word(wid, word, translation, topic, example, age_group="8_10"):
    """Слово-строка для image-вопроса: ключи, которые _word_dict читает напрямую."""
    return {
        "id": wid,
        "word": word,
        "translation": translation,
        "transcription": "",
        "example": example,
        "topic": topic,
        "age_group": age_group,
    }


class QuizImageTypeRemovedTests(unittest.IsolatedAsyncioTestCase):
    """Карточки без картинок: тип вопроса «image» убран. Запрос qtype='image' мягко
    откатывается в 'translation' (guard `qtype not in rotation`), а ротация по индексу
    никогда не выдаёт тип 'image'. БД не вызывается (пул достаточный)."""

    async def _question(self, word, qtype=None, index=0):
        pool = _pool(10)  # достаточно дистракторов -> обращений в БД быть не должно
        with patch("database.get_word_options", new=AsyncMock(side_effect=AssertionError)), \
             patch("database.get_random_words", new=AsyncMock(side_effect=AssertionError)):
            return await _build_vocab_question(word, "8_10", index=index, qtype=qtype, pool=pool)

    async def test_image_qtype_falls_back_to_translation(self):
        q = await self._question(
            _img_word(1, "apple", "яблоко", "food", "I eat an apple every day."),
            qtype="image",
        )
        self.assertEqual(q["type"], "translation")
        self.assertEqual(q["prompt"], "Выбери перевод")
        self.assertEqual(q["word"], "apple", "в translation показываем само слово")
        self.assertEqual(q["translation"], "", "перевод не утекает в подсказку")
        labels = [o["label"] for o in q["options"]]
        self.assertIn("яблоко", labels, "правильный перевод среди вариантов")

    async def test_rotation_never_yields_image_type(self):
        word = _img_word(1, "lesson", "урок", "school", "We have an English lesson today.")
        seen = set()
        for index in range(8):
            q = await self._question(word, index=index)
            seen.add(q["type"])
        self.assertNotIn("image", seen, f"тип 'image' не должен появляться: {sorted(seen)}")


if __name__ == "__main__":
    unittest.main()
