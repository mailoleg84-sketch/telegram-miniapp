"""Тесты оркестрации голосового хода (_voice_text_turn_payload).

После параллелизации через asyncio.gather проверяем, что порядок и состав
операций сохранён: 2 записи сообщений (user+assistant), учёт usage, корректная
ветка лимита. БД и модель замоканы — тестируется только оркестрация.
"""
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from webapp import server


def _stats(requests=0):
    return {
        "requests": requests,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0,
    }


_USER = {"name": "Kid", "age_group": "8_10", "goal": "speaking", "child_age": 9}


class VoiceTurnPayloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_turn_persists_messages_and_usage(self):
        reply = SimpleNamespace(
            text="Привет!", model="m",
            input_tokens=1, output_tokens=2, total_tokens=3, cost_usd=0.001,
        )
        add_msg = AsyncMock()
        add_usage = AsyncMock()
        with ExitStack() as es:
            p = es.enter_context
            p(patch("database.get_ai_usage_today", AsyncMock(return_value=_stats())))
            p(patch("database.get_user", AsyncMock(return_value=_USER)))
            p(patch("database.add_message", add_msg))
            p(patch("database.add_ai_usage", add_usage))
            p(patch("database.get_recent_messages", AsyncMock(return_value=[])))
            # Голосовой ход живёт в webapp/routes_chat_voice.py (шаг 3e-3) —
            # патчим имена в его пространстве; server реэкспортирует функцию.
            p(patch("webapp.routes_chat_voice._advance_voice_lesson_state",
                    AsyncMock(return_value={"phase": "dialogue"})))
            p(patch("webapp.routes_chat_voice.chat_reply", AsyncMock(return_value=reply)))
            p(patch("webapp.routes_chat_voice._voice_prompt_context", MagicMock(return_value={})))
            p(patch("webapp.routes_chat_voice._prompt_context_for_user", MagicMock(return_value={})))
            p(patch("webapp.routes_chat_voice.public_lesson_state",
                    MagicMock(return_value={"phase": "dialogue"})))
            result = await server._voice_text_turn_payload(123, "hi there")

        self.assertEqual(result["reply"], "Привет!")
        self.assertEqual(result["text"], "hi there")
        self.assertEqual(result["lesson_state"], {"phase": "dialogue"})
        # Ровно две записи в историю — пользователь, затем ассистент.
        self.assertEqual(add_msg.await_count, 2)
        roles = [call.args[1] for call in add_msg.await_args_list]
        self.assertEqual(roles, ["user", "assistant"])
        add_usage.assert_awaited_once()

    async def test_voice_turn_limit_reached_short_circuits(self):
        add_msg = AsyncMock()
        with ExitStack() as es:
            p = es.enter_context
            p(patch("webapp.routes_chat_voice.AI_DAILY_MESSAGE_LIMIT", 10))
            p(patch("database.get_ai_usage_today", AsyncMock(return_value=_stats(requests=999))))
            p(patch("database.get_user", AsyncMock(return_value=_USER)))
            p(patch("database.add_message", add_msg))
            p(patch("webapp.routes_chat_voice._ensure_voice_lesson_state",
                    AsyncMock(return_value={"phase": "welcome"})))
            p(patch("webapp.routes_chat_voice.public_lesson_state",
                    MagicMock(return_value={"phase": "welcome"})))
            result = await server._voice_text_turn_payload(123, "hi there")

        self.assertTrue(result["limit_reached"])
        self.assertTrue(result["reply"])
        # При лимите сообщения НЕ сохраняются.
        add_msg.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
