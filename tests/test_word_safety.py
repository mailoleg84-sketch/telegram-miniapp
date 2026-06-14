"""Страж детской безопасности и чистоты банка слов.

Слова сидятся в таблицу `words` только если их нет в BLOCKED_SEED_WORDS
(database._seed_words фильтрует так же). Проверяем, что недетские слова, слуры,
оружие и мусорные аббревиатуры НЕ попадают в посеянный набор, а исправленные
переводы не «уехали» обратно.
"""
import unittest

from data.single_words_5000 import SINGLE_WORDS_5000
from data.words import LEARNING_WORDS
from database import BLOCKED_SEED_WORDS


def _seeded_words() -> set[str]:
    """Набор слов, реально попадающих в БД (как в _seed_words)."""
    return {
        w[0].strip().lower()
        for w in LEARNING_WORDS
        if w[0].strip().lower() not in BLOCKED_SEED_WORDS
    }


class WordBankSafetyTests(unittest.TestCase):
    def test_forbidden_words_never_seeded(self):
        forbidden = {
            # слуры / оскорбительное
            "blacks", "negro", "nigger", "faggot", "retard",
            # оружие / насилие
            "knife", "blade", "gun", "rob", "punch", "stab", "kill",
            # сленг / недетское
            "bro", "dude", "bucks", "bar", "bars", "boyfriend", "bet", "buried",
            # мусорные аббревиатуры / не-слова
            "abc", "aug", "dec", "jan", "feb", "mar", "oct", "nov",
            "del", "des", "der", "com", "etc",
        }
        leaked = sorted(forbidden & _seeded_words())
        self.assertEqual(leaked, [], f"недопустимые слова всё ещё сидятся детям: {leaked}")

    def test_slur_is_blocked(self):
        # Слур заблокирован при сидинге И в источнике перевод нейтрализован.
        self.assertIn("blacks", BLOCKED_SEED_WORDS)
        src = {w[0].lower(): w[1] for w in SINGLE_WORDS_5000}
        self.assertNotIn("негр", src.get("blacks", "").lower())

    def test_function_word_translations_are_correct(self):
        src = {w[0].lower(): w[1] for w in SINGLE_WORDS_5000}
        self.assertEqual(src.get("the"), "определённый артикль")
        self.assertEqual(src.get("an"), "неопределённый артикль")
        self.assertEqual(src.get("afternoon"), "время после полудня")
        self.assertEqual(src.get("ash"), "пепел")
        self.assertEqual(src.get("arms"), "руки")
        self.assertEqual(src.get("branches"), "ветки")


if __name__ == "__main__":
    unittest.main()
