"""Глобальный суточный потолок расходов OpenAI (_ai_budget_exceeded).

Защита от runaway-затрат по всем пользователям. БД-подсчёт замокан.
"""
import unittest
from unittest.mock import AsyncMock, patch

from webapp import routes_chat_voice as rcv


class AiBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self):
        with patch.object(rcv, "OPENAI_DAILY_COST_LIMIT_USD", 0):
            self.assertFalse(await rcv._ai_budget_exceeded())

    async def test_under_limit(self):
        with patch.object(rcv, "OPENAI_DAILY_COST_LIMIT_USD", 10.0), \
             patch("database.get_ai_cost_today_total", AsyncMock(return_value=3.0)):
            self.assertFalse(await rcv._ai_budget_exceeded())

    async def test_over_limit_blocks(self):
        with patch.object(rcv, "OPENAI_DAILY_COST_LIMIT_USD", 10.0), \
             patch("database.get_ai_cost_today_total", AsyncMock(return_value=10.5)):
            self.assertTrue(await rcv._ai_budget_exceeded())

    async def test_count_error_fails_open(self):
        # Сбой подсчёта не должен блокировать детей (учёт ≠ доступность).
        with patch.object(rcv, "OPENAI_DAILY_COST_LIMIT_USD", 10.0), \
             patch("database.get_ai_cost_today_total", AsyncMock(side_effect=RuntimeError)):
            self.assertFalse(await rcv._ai_budget_exceeded())


if __name__ == "__main__":
    unittest.main()
