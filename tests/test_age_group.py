"""Тесты единой «лестницы» возраст→группа (config.age_group_from_age) и
сохранения РАЗНОЙ семантики нормализации в learning- и voice-режимах.
"""
import unittest

from config import age_group_from_age
from webapp.server import _age_group_from_age, _normalized_age_group_for_user
from webapp.openai_service import _normalize_realtime_age_group


class AgeLadderTests(unittest.TestCase):
    def test_age_to_group_mapping(self):
        self.assertEqual(age_group_from_age(6), "5_7")
        self.assertEqual(age_group_from_age(9), "8_10")
        self.assertEqual(age_group_from_age(12), "11_13")
        self.assertEqual(age_group_from_age(16), "14_18")

    def test_out_of_range_and_garbage(self):
        self.assertEqual(age_group_from_age(4), "")
        self.assertEqual(age_group_from_age(19), "")
        self.assertEqual(age_group_from_age(None), "")
        self.assertEqual(age_group_from_age("abc"), "")
        self.assertEqual(age_group_from_age("10"), "8_10")  # числовая строка ок

    def test_server_helper_delegates(self):
        self.assertEqual(_age_group_from_age(9), "8_10")
        self.assertEqual(_age_group_from_age(4), "")


class DistinctSemanticsTests(unittest.TestCase):
    def test_learning_mode_prefers_stored_group(self):
        # learning: сохранённая каноническая группа важнее возраста.
        self.assertEqual(
            _normalized_age_group_for_user({"age_group": "14_18", "child_age": 9}),
            "14_18",
        )
        # Невалидная группа -> вывод из возраста.
        self.assertEqual(
            _normalized_age_group_for_user({"age_group": "legacy", "child_age": 9}),
            "8_10",
        )

    def test_voice_mode_prefers_exact_age(self):
        # voice/realtime: точный возраст важнее сохранённой группы.
        self.assertEqual(_normalize_realtime_age_group("14_18", 9), "8_10")
        # Нет возраста, легаси-токен -> 8_10.
        self.assertEqual(_normalize_realtime_age_group("under_12", None), "8_10")
        # Совсем неизвестно -> "default" (особый фолбэк voice-режима).
        self.assertEqual(_normalize_realtime_age_group("weird", None), "default")


if __name__ == "__main__":
    unittest.main()
