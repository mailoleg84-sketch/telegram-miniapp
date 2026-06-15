"""Страж: каждое целевое ОДИНОЧНОЕ слово из topic_plans есть в банке слов.

Если лесенка тем ссылается на слово, которого нет в LEARNING_WORDS, урок не
сможет дать карточку/перевод/озвучку. (Фразы из нескольких слов — напр.
«sounds good» — сюда не входят: они матчатся алиасами, а не как карточки.)
"""
import unittest

from data.topic_plans import TOPIC_PLANS
from data.words import LEARNING_WORDS


class TopicPlanWordsTests(unittest.TestCase):
    def test_single_word_targets_present_in_bank(self):
        bank = {w[0].lower() for w in LEARNING_WORDS}
        missing = []
        for age, plans in TOPIC_PLANS.items():
            for plan in plans:
                for target in plan["words"]:
                    t = target.lower().strip()
                    if " " in t:
                        continue  # фраза, не словарная карточка
                    if t not in bank:
                        missing.append((age, plan["id"], target))
        self.assertEqual(missing, [], f"целевые слова не в банке: {missing}")

    def test_added_words_present(self):
        bank = {w[0].lower() for w in LEARNING_WORDS}
        for w in ("doll", "sunny", "rainy", "playlist", "luggage", "booking"):
            self.assertIn(w, bank, w)


if __name__ == "__main__":
    unittest.main()
