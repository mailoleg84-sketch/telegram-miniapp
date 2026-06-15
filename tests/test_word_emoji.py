"""Покрытие эмодзи для слов 11–18 (image-вопрос даётся только словам с эмодзи —
см. server.py api где qtype 'image' откатывается на 'translation' без эмодзи).

Страж от случайного удаления/опечатки в WORD_EMOJI.
"""
import unittest

from webapp.vocabulary_visualizer import emoji_for

# Целевые слова 11–18, ради которых расширяли покрытие (точное соответствие глифа).
EXPECTED_11_18 = {
    "officer": "👮", "detective": "🕵️", "scientist": "🧑‍🔬", "engineer": "👷",
    "developer": "🧑‍💻", "newspaper": "🗞️", "telescope": "🔭", "microscope": "🔬",
    "satellite": "🛰️", "exam": "📝", "factory": "🏭", "galaxy": "🌌",
    "diamond": "💎", "crown": "👑", "shield": "🛡️", "alien": "👽",
}

# Кросс-возрастные слова, закрытые тем же проходом — должны иметь эмодзи.
ALSO_COVERED = (
    "king", "queen", "calendar", "battery", "mirror",
    "brush", "hammer", "gear", "chain", "flag", "bell", "lock", "coin",
    "dollar", "ring", "medal", "trophy", "wheel", "cherry", "chocolate",
    "pepper", "salt", "dragon", "rooster", "bat", "bridge", "castle", "tower",
    "island", "desert", "planet", "stadium", "bank", "baseball",
    "boxing", "golf", "fishing", "brain", "bone",
)


class WordEmojiTests(unittest.TestCase):
    def test_11_18_words_have_exact_emoji(self):
        for word, glyph in EXPECTED_11_18.items():
            self.assertEqual(emoji_for(word), glyph, f"эмодзи для {word!r}")

    def test_cross_age_words_have_emoji(self):
        for word in ALSO_COVERED:
            self.assertTrue(emoji_for(word), f"нет эмодзи для {word!r}")

    def test_no_collision_newspaper_vs_magazine(self):
        # newspaper и magazine — оба «пресса»; глифы должны различаться, иначе
        # image-вопрос становится неоднозначным (📰 уже занят magazine).
        self.assertNotEqual(emoji_for("newspaper"), emoji_for("magazine"))


if __name__ == "__main__":
    unittest.main()
