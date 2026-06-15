"""Курированная реклассификация тем (data/words._TOPIC_OVERRIDE).

Страж: переезды применяются, омонимы не задеты, все целевые темы — валидные
темы-колоды (VOCAB_TOPIC_LABELS).
"""
import unittest

from data.words import LEARNING_WORDS, _TOPIC_OVERRIDE

# Темы-колоды (зеркало webapp.server.VOCAB_TOPIC_LABELS) — целевые темы override
# должны быть только из этого набора.
DECK_TOPICS = {
    "animals", "food", "school", "colors", "nature", "body", "family",
    "sports", "travel", "home", "toys", "clothes", "transport", "music",
    "technology", "feelings", "hobbies", "work",
}


class TopicReclassifyTests(unittest.TestCase):
    def setUp(self):
        self.topic_by_word = {w[0].lower(): w[3] for w in LEARNING_WORDS}

    def test_movers_applied(self):
        for word, expected in [
            ("cherry", "food"), ("bone", "body"), ("train", "transport"),
            ("piano", "music"), ("rooster", "animals"), ("island", "nature"),
            ("jacket", "clothes"), ("wife", "family"), ("trophy", "sports"),
        ]:
            self.assertEqual(self.topic_by_word.get(word), expected, word)

    def test_homonyms_not_misclassified(self):
        # rock=рок (жанр), seal=печать, sink=тонуть — не должны уехать в
        # nature/animals/home из-за совпадения написания.
        self.assertNotEqual(self.topic_by_word.get("rock"), "nature")
        self.assertNotEqual(self.topic_by_word.get("seal"), "animals")
        self.assertNotEqual(self.topic_by_word.get("sink"), "home")

    def test_all_targets_are_deck_topics(self):
        for word, topic in _TOPIC_OVERRIDE.items():
            self.assertIn(topic, DECK_TOPICS, f"{word} -> {topic}")

    def test_word_count_unchanged(self):
        self.assertEqual(len(LEARNING_WORDS), 5000)


if __name__ == "__main__":
    unittest.main()
