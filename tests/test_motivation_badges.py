"""Лестница достижений (_motivation_payload) — расширенные вехи.

Проверяет наличие новых вех (100/250 слов, 14/30 дней и т.п.), корректную
разблокировку у «сильного» профиля и блокировку у новичка.
"""
import unittest

from webapp.server import _motivation_payload

NEW_MILESTONES = (
    "two_week_streak", "month_streak", "ten_lessons", "thirty_lessons",
    "word_explorer", "word_master", "test_regular", "game_fan",
    "sharp_answer", "expert_answer",
)


def _payload(words=0, correct=0, wrong=0, lessons=0, tests=0, games=0, streak=0, review=0, today=False):
    user = {"name": "Тест"}
    stats = {"words_learned": words, "total_correct": correct, "total_wrong": wrong}
    dictionary_summary = {"review_words": review}
    report = {"completed_lessons": lessons, "completed_word_tests": tests, "completed_games": games}
    streak_d = {"current_streak": streak, "longest_streak": streak,
                "completed_days": lessons, "today_completed": today}
    return _motivation_payload(user, stats, dictionary_summary, report, streak_d)


class MotivationBadgesTests(unittest.TestCase):
    def test_new_milestones_present(self):
        p = _payload()
        ids = {b["id"] for b in p["badges"]}
        for bid in NEW_MILESTONES:
            self.assertIn(bid, ids)
        self.assertEqual(p["summary"]["total_badges"], len(p["badges"]))

    def test_high_achiever_unlocks_all_milestones(self):
        p = _payload(words=300, correct=300, lessons=40, tests=15, games=12, streak=30)
        unlocked = {b["id"] for b in p["badges"] if b["unlocked"]}
        for bid in NEW_MILESTONES:
            self.assertIn(bid, unlocked)
        self.assertEqual(p["summary"]["unlocked_badges"], len(p["badges"]))

    def test_beginner_locks_top_milestones(self):
        p = _payload(words=5, correct=2, lessons=1, streak=1)
        locked = {b["id"] for b in p["badges"] if not b["unlocked"]}
        for bid in ("word_master", "month_streak", "expert_answer", "thirty_lessons"):
            self.assertIn(bid, locked)


if __name__ == "__main__":
    unittest.main()
