"""Инварианты «живых примеров» к словам (data/words.py, шаг плана 5.2).

Примеры генерируются детерминированно из слова/части речи/возраста (а не один
шаблон на все 5000). Эти страж-проверки фиксируют контракт, на который опирается
рантайм (карточки слова, gap-вопросы) и безопасность детского контента.
"""
import re
import unittest

from data.words import (
    LEARNING_WORDS,
    _build_example,
    _example_category,
)


class WordExampleInvariantTests(unittest.TestCase):
    def test_every_example_contains_target_word(self):
        """Gap-вопрос прячет слово в примере (regex \\bword\\b) — слово обязано в
        примере быть, иначе тип «вставь пропущенное слово» не предложится."""
        missing = [
            (word, example)
            for word, _tr, example, _tp, _ag, _trc in LEARNING_WORDS
            if not re.search(rf"\b{re.escape(word)}\b", example, re.IGNORECASE)
        ]
        self.assertEqual(missing, [], f"Примеры без целевого слова (до 5): {missing[:5]}")

    def test_no_legacy_template_and_bounded_length(self):
        """Старый монотонный шаблон вычищен; примеры короткие и непустые."""
        for word, _tr, example, _tp, _ag, _trc in LEARNING_WORDS:
            self.assertTrue(example.strip(), f"Пустой пример у {word!r}")
            self.assertLessEqual(len(example), 80, f"Слишком длинный пример у {word!r}: {example!r}")
            self.assertFalse(
                example.startswith("Let's learn the word "),
                f"Остался старый шаблон у {word!r}",
            )

    def test_examples_are_deterministic(self):
        """Генерация стабильна (sha1, без random/hash-соли) — один и тот же вход
        даёт один и тот же пример при повторном построении."""
        for word, translation, example, topic, age_group, _trc in LEARNING_WORDS[:200]:
            self.assertEqual(_build_example(word, translation, topic, age_group), example)

    def test_function_words_use_quoted_frame_not_usage(self):
        """Служебные слова не получают «живой» пример употребления (он был бы
        кривым) — только фрейм с упоминанием слова в кавычках."""
        for word in ("and", "the", "about", "always", "have", "another"):
            rows = [r for r in LEARNING_WORDS if r[0] == word]
            if not rows:
                continue
            example = rows[0][2]
            self.assertIn(f"'{word}'", example.lower(), f"{word!r}: {example!r}")
            self.assertEqual(_example_category(word, rows[0][1], rows[0][3]), "func")

    def test_curated_and_extra_core_get_real_usage(self):
        """Курируемое ядро + расширение дают настоящий пример (не фрейм-кавычки)."""
        for word in ("book", "car", "bear", "apple", "dog", "run", "tall", "huge"):
            rows = [r for r in LEARNING_WORDS if r[0] == word]
            self.assertTrue(rows, f"{word!r} нет в LEARNING_WORDS")
            self.assertNotIn("'", rows[0][2], f"{word!r} получил фрейм-кавычки: {rows[0][2]!r}")


class BlockedSeedWordsGuardTests(unittest.TestCase):
    """Страж safety-слоя: одиозные слова из аудита банка не должны вернуться
    в детский банк (фильтруются BLOCKED_SEED_WORDS в database._seed_words)."""

    def test_egregious_words_are_blocked(self):
        from database import BLOCKED_SEED_WORDS

        for word in (
            "blacks", "wtf", "sucks", "suck", "knife", "blade", "bullet", "shoot",
            "idiot", "stupid", "dumb", "died", "funeral", "gay", "jews", "nuclear",
            "abortion", "smoke", "drug", "drugs",
        ):
            self.assertIn(word, BLOCKED_SEED_WORDS, f"{word!r} обязан быть в блок-листе")


if __name__ == "__main__":
    unittest.main()
