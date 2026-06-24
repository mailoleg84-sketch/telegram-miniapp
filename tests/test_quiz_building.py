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


class BuildVocabImageQuestionTests(unittest.IsolatedAsyncioTestCase):
    """qtype='image' показывает не только эмодзи, но и безопасную учебную SVG-сцену
    для слов без эмодзи (lesson/class/visited/because); grammar/context-only слова
    (the) в картинку не уходят. Archetype берётся из реального
    build_vocabulary_visual (как на проде); БД не вызывается (пул достаточный)."""

    async def _image_question(self, word):
        pool = _pool(10)  # достаточно дистракторов -> обращения в БД быть не должно
        with patch("database.get_word_options", new=AsyncMock(side_effect=AssertionError)), \
             patch("database.get_random_words", new=AsyncMock(side_effect=AssertionError)):
            return await _build_vocab_question(word, "8_10", qtype="image", pool=pool)

    async def test_visited_stays_image_action_scene(self):
        q = await self._image_question(
            _img_word(1, "visited", "посетил", "travel", "She visited the zoo with her family.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Что делает герой?")
        self.assertTrue(q["image_url"], "должна быть учебная SVG-сцена")
        self.assertEqual(q["emoji"], "")
        self.assertEqual(q["translation"], "", "перевод не должен утекать в image-вопрос")

    async def test_lesson_stays_image_context_scene(self):
        q = await self._image_question(
            _img_word(1, "lesson", "урок", "school", "We have an English lesson today.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Что означает эта ситуация?")
        self.assertTrue(q["image_url"])
        self.assertEqual(q["emoji"], "")

    async def test_class_stays_image_context_scene(self):
        q = await self._image_question(
            _img_word(1, "class", "класс", "school", "Our class is learning new words.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Что означает эта ситуация?")
        self.assertTrue(q["image_url"])

    async def test_because_stays_image_cause_effect(self):
        q = await self._image_question(
            _img_word(1, "because", "потому что", "grammar", "He is wet because it is raining.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Какое слово объясняет причину или результат?")
        self.assertTrue(q["image_url"])

    async def test_the_is_not_image_falls_back(self):
        q = await self._image_question(
            _img_word(1, "the", "артикль the", "basic", "I see the cat.")
        )
        self.assertIn(q["type"], {"gap", "word"})
        self.assertEqual(q["image_url"], "")
        self.assertEqual(q["emoji"], "")
        expected = "Вставь пропущенное слово" if q["type"] == "gap" else "Выбери английское слово"
        self.assertEqual(q["prompt"], expected)

    async def test_apple_with_emoji_keeps_glyph(self):
        q = await self._image_question(
            _img_word(1, "apple", "яблоко", "food", "I eat an apple every day.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Что это?")
        self.assertTrue(q["emoji"], "у apple должен быть эмодзи-глиф")
        self.assertEqual(q["image_url"], "", "emoji-слова показывают глиф, не сцену")

    async def test_answer_stays_image_scene_not_photo(self):
        # answer теперь учебная сцена (не object-фото руки/анкеты): остаётся image
        # с вопросом «что означает ситуация», без /vocabulary-photo.
        q = await self._image_question(
            _img_word(1, "answer", "ответ", "school", "Please answer the question.")
        )
        self.assertEqual(q["type"], "image")
        self.assertEqual(q["prompt"], "Что означает эта ситуация?")
        self.assertTrue(q["image_url"] or q["emoji"], "должна быть сцена или эмодзи")
        self.assertNotIn("/vocabulary-photo", q["image_url"])


if __name__ == "__main__":
    unittest.main()
