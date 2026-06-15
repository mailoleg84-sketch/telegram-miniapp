"""Ежедневные напоминания ботом (webapp/reminders).

Покрывает: текст (со стриком/без, с именем/без), секрет-гейт cron (fail-closed),
и цикл рассылки с моками бота и БД (успех + авто-выключение заблокировавших).
"""
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramForbiddenError

from webapp import reminders


class ReminderTextTests(unittest.TestCase):
    def test_streak_message_mentions_streak_and_name(self):
        t = reminders.build_reminder_text("Аня", 5)
        self.assertIn("5", t)
        self.assertIn("Аня", t)
        self.assertIn("серия", t)

    def test_threshold_one_day_is_generic(self):
        # 1 день — без слова «серия» (это generic-приглашение), 2+ — про серию.
        self.assertNotIn("серия", reminders.build_reminder_text("", 1))
        self.assertIn("серия", reminders.build_reminder_text("", 2))

    def test_generic_message_without_name(self):
        t = reminders.build_reminder_text("", 0)
        self.assertTrue(t.strip())
        self.assertIn("Привет", t)


class CronSecretTests(unittest.TestCase):
    def test_disabled_when_secret_empty(self):
        with patch.object(reminders, "REMINDER_CRON_SECRET", ""):
            self.assertFalse(reminders.is_configured())
            self.assertFalse(reminders.cron_secret_ok(""))
            self.assertFalse(reminders.cron_secret_ok("anything"))

    def test_match_required(self):
        with patch.object(reminders, "REMINDER_CRON_SECRET", "topsecret"):
            self.assertTrue(reminders.is_configured())
            self.assertTrue(reminders.cron_secret_ok("topsecret"))
            self.assertTrue(reminders.cron_secret_ok("  topsecret  "))
            self.assertFalse(reminders.cron_secret_ok("wrong"))
            self.assertFalse(reminders.cron_secret_ok(""))


class SendRemindersTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_bot_returns_error(self):
        res = await reminders.send_daily_reminders(None)
        self.assertEqual(res["sent"], 0)
        self.assertIn("error", res)

    async def test_sends_and_marks_sent(self):
        bot = AsyncMock()
        with patch("database.get_reminder_candidates", AsyncMock(return_value=[{"user_id": 1, "name": "Аня"}])), \
             patch("database.get_learning_streak", AsyncMock(return_value={"current_streak": 3})), \
             patch("database.set_reminder_sent", AsyncMock()) as sent_mock, \
             patch("database.set_reminders_enabled", AsyncMock()) as disable_mock:
            res = await reminders.send_daily_reminders(bot)
        self.assertEqual(res["sent"], 1)
        self.assertEqual(res["disabled"], 0)
        bot.send_message.assert_awaited_once()
        sent_mock.assert_awaited_once_with(1)
        disable_mock.assert_not_awaited()

    async def test_blocked_user_auto_disabled(self):
        bot = AsyncMock()
        bot.send_message.side_effect = TelegramForbiddenError(method=None, message="bot blocked")
        with patch("database.get_reminder_candidates", AsyncMock(return_value=[{"user_id": 7, "name": ""}])), \
             patch("database.get_learning_streak", AsyncMock(return_value={"current_streak": 0})), \
             patch("database.set_reminder_sent", AsyncMock()) as sent_mock, \
             patch("database.set_reminders_enabled", AsyncMock()) as disable_mock:
            res = await reminders.send_daily_reminders(bot)
        self.assertEqual(res["sent"], 0)
        self.assertEqual(res["disabled"], 1)
        disable_mock.assert_awaited_once_with(7, False)
        sent_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
