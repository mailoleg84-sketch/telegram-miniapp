"""Высокоточная классификация тем по смыслу (data/topic_classifier) для 20 колод.

Страж: уверенные слова уезжают в правильную тему-колоду, неуверенные/омонимы
остаются в общем словаре (не попадают в колоду), тем-колод ровно 20, слов 5006.
"""
import unittest
from collections import Counter

from data.topic_classifier import CANONICAL_TOPICS, classify_topic
from data.words import LEARNING_WORDS
from webapp.vocabulary_visualizer import determine_part_of_speech


def _canon(word, translation, topic="everyday"):
    pos = determine_part_of_speech(word, translation, topic)
    return classify_topic(word, translation, pos, topic)


class TopicClassifierTests(unittest.TestCase):
    def setUp(self):
        self.topic_by_word = {w[0].lower(): w[3] for w in LEARNING_WORDS}

    def test_exactly_twenty_deck_topics(self):
        self.assertEqual(len(CANONICAL_TOPICS), 20)

    def test_confident_words_land_in_right_topic(self):
        cases = {
            "cherry": "food", "bone": "body", "train": "travel", "rooster": "animals",
            "island": "nature", "jacket": "clothes", "wife": "people", "trophy": "sports",
            "piano": "art", "computer": "technology",
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(self.topic_by_word.get(word), expected, word)

    def test_uncertain_words_stay_out_of_decks(self):
        # Абстрактные/служебные слова не классифицируются -> сохраняют исходную тему
        # (не из набора колод) и живут в общем словаре.
        for word in ("age", "air", "aim", "alarm", "about"):
            with self.subTest(word=word):
                self.assertNotIn(self.topic_by_word.get(word), CANONICAL_TOPICS, word)

    def test_no_substring_misclassification(self):
        # Подстрочных ляпов нет (совпадение по началу слова, а не где попало):
        self.assertNotEqual(_canon("alarm", "сигнализация"), "body")   # не «arm»
        self.assertNotEqual(_canon("dear", "дорогой"), "body")          # не «ear»
        self.assertNotEqual(_canon("chat", "чат"), "clothes")           # не «hat»
        self.assertNotEqual(_canon("been", "был"), "animals")           # не «bee»
        self.assertNotEqual(_canon("around", "вокруг"), "colors")       # не «round»

    def test_homonyms_excluded(self):
        for word in ("bow", "back", "seal", "match", "club"):
            with self.subTest(word=word):
                self.assertIsNone(_canon(word, "перевод"))

    def test_all_deck_topics_filled(self):
        cnt = Counter(self.topic_by_word.values())
        for key in CANONICAL_TOPICS:
            with self.subTest(topic=key):
                self.assertGreaterEqual(cnt[key], 6, f"{key}: {cnt[key]}")

    def test_word_count_base_plus_extra(self):
        # 5000 базовых + 6 целевых из topic_plans + курированные тематические
        # слова (data/topic_extra_words, семь волн). Слова только добавляются.
        self.assertEqual(len(LEARNING_WORDS), 7569)

    def test_curated_extra_words_land_in_their_topic(self):
        # Курированные тематические слова получают заявленную тему напрямую
        # (без реклассификации) и наполняют колоды.
        cases = {
            "giraffe": "animals", "yogurt": "food", "sweater": "clothes",
            "elbow": "body", "curtain": "home", "notebook": "school",
            "waterfall": "nature", "triangle": "colors", "helicopter": "travel",
            "keyboard": "technology", "violin": "art", "dentist": "work",
            "hospital": "places", "conversation": "communication",
        }
        for word, expected in cases.items():
            with self.subTest(word=word):
                self.assertEqual(self.topic_by_word.get(word), expected, word)

    def test_no_duplicate_words_after_extra(self):
        # Дедуп против банка: одно англ. слово — одна запись.
        words = [w[0].strip().lower() for w in LEARNING_WORDS]
        self.assertEqual(len(words), len(set(words)))


if __name__ == "__main__":
    unittest.main()
