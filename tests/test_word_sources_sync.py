"""Инвариант единого источника переводов.

Курируемые слова (CORE_WORDS в data/words.py) пересекаются с массовым банком
(SINGLE_WORDS_5000 в data/single_words_5000.py). Перевод одного и того же слова
должен совпадать в обоих источниках — иначе ребёнок может увидеть разный перевод
в зависимости от того, какой источник победил при слиянии.

Тест-страж от дрейфа (аудит «нет единого источника»): если кто-то поправит
перевод в одном файле и забудет в другом, тест упадёт. Диагностика на момент
добавления: пересечение 40 слов, 0 конфликтов.
"""
import unittest

from data.words import CORE_WORDS
from data.single_words_5000 import SINGLE_WORDS_5000


def _first_translation_map(rows):
    """word(lower) -> перевод (первое вхождение, как при слиянии через `seen`)."""
    out = {}
    for row in rows:
        word = str(row[0]).strip().lower()
        out.setdefault(word, str(row[1]).strip())
    return out


class WordSourceTranslationSyncTests(unittest.TestCase):
    def test_core_and_bulk_translations_agree(self):
        core = _first_translation_map(CORE_WORDS)
        bulk = _first_translation_map(SINGLE_WORDS_5000)
        conflicts = sorted(
            (word, core[word], bulk[word])
            for word in set(core) & set(bulk)
            if core[word] != bulk[word]
        )
        self.assertEqual(
            conflicts,
            [],
            f"Переводы CORE_WORDS и SINGLE_WORDS_5000 разошлись (показаны до 10): {conflicts[:10]}",
        )


if __name__ == "__main__":
    unittest.main()
