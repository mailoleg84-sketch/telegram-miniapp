"""Интеграционные тесты aiohttp-приложения: авторизация, заголовки, статика,
rate-limit. Не требуют реальной БД — где нужно, database мокается.
"""
import asyncio
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

from aiohttp.test_utils import AioHTTPTestCase

from webapp.server import create_app, _rate_limit_ok, _rate_buckets
from webapp.auth import make_fallback_auth_params


def _fallback_header(user_id: int = 4242, name: str = "Tester") -> str:
    """Подписанная fallback-авторизация в виде query-строки для заголовка."""
    return urlencode(make_fallback_auth_params(user_id, name))


class ServerIntegrationTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_api_without_auth_is_unauthorized(self):
        resp = await self.client.get("/api/me")
        self.assertEqual(resp.status, 401)

    async def test_api_with_invalid_init_data_is_unauthorized(self):
        resp = await self.client.get(
            "/api/me",
            headers={"X-Telegram-Init-Data": "garbage=1&hash=deadbeef"},
        )
        self.assertEqual(resp.status, 401)

    async def test_valid_fallback_auth_passes_middleware(self):
        # Пользователь не зарегистрирован -> 403 (а НЕ 401): значит подпись
        # принята middleware и отклонён уже шаг проверки регистрации.
        with patch("database.user_exists", new=AsyncMock(return_value=False)):
            resp = await self.client.get(
                "/api/dictionary",
                headers={"X-App-Fallback-Auth": _fallback_header()},
            )
        self.assertEqual(resp.status, 403)

    async def test_realtime_token_timeout_returns_friendly_504(self):
        # При таймауте выдачи токена отдаём дружелюбный 504, а не висим ~50с.
        stats = {"requests": 0, "input_tokens": 0, "output_tokens": 0,
                 "total_tokens": 0, "cost_usd": 0}
        user = {"name": "Kid", "age_group": "8_10", "child_age": 9, "goal": "speaking"}
        with ExitStack() as es:
            p = es.enter_context
            p(patch("database.user_exists", AsyncMock(return_value=True)))
            p(patch("database.get_ai_usage_today", AsyncMock(return_value=stats)))
            p(patch("database.get_user", AsyncMock(return_value=user)))
            p(patch("database.get_model_requests_today", AsyncMock(return_value=0)))
            p(patch("database.get_recent_messages", AsyncMock(return_value=[])))
            # Realtime-маршруты живут в webapp/routes_chat_voice.py (шаг 3e-3).
            p(patch("webapp.routes_chat_voice._ensure_voice_lesson_state", AsyncMock(return_value={})))
            p(patch("webapp.routes_chat_voice._realtime_prompt_context", MagicMock(return_value={})))
            p(patch("webapp.routes_chat_voice.create_realtime_client_secret",
                    AsyncMock(side_effect=asyncio.TimeoutError())))
            resp = await self.client.post(
                "/api/realtime/token",
                headers={"X-App-Fallback-Auth": _fallback_header(990, "Kid")},
            )
        self.assertEqual(resp.status, 504)
        body = await resp.json()
        self.assertIn("error", body)

    async def test_security_headers_present_on_index(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", resp.headers)
        self.assertIn("default-src 'self'", resp.headers["Content-Security-Policy"])

    async def test_index_served_with_no_store(self):
        resp = await self.client.get("/")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))

    async def test_static_js_is_gzipped_and_cacheable(self):
        resp = await self.client.get(
            "/static/app.js",
            headers={"Accept-Encoding": "gzip"},
            auto_decompress=False,
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")
        self.assertIn("max-age", resp.headers.get("Cache-Control", ""))

    async def test_api_json_response_is_gzipped(self):
        # API-JSON тоже должен сжиматься (особенно тяжёлый /api/dictionary).
        # Берём успешный 200-JSON: пользователь есть, словарь замокан.
        words = [{"id": i, "word": f"w{i}", "translation": "x", "transcription": "",
                  "example": "", "topic": "basic", "age_group": "8_10",
                  "correct_count": 0, "wrong_count": 0, "needs_review": False,
                  "mastered": False} for i in range(60)]
        summary = {"total_words": 60, "mastered_words": 0, "review_words": 0}
        with ExitStack() as es:
            p = es.enter_context
            p(patch("database.user_exists", AsyncMock(return_value=True)))
            p(patch("database.get_user", AsyncMock(return_value={"age_group": "8_10"})))
            p(patch("database.get_user_dictionary", AsyncMock(return_value=words)))
            p(patch("database.get_dictionary_summary", AsyncMock(return_value=summary)))
            # get_words_count тоже должен быть замокан — иначе хэндлер лезет в живую
            # БД (Neon) и тест становится зависимым от окружения/паролей.
            p(patch("database.get_words_count", AsyncMock(return_value=60)))
            resp = await self.client.get(
                "/api/dictionary",
                headers={"X-App-Fallback-Auth": _fallback_header(771, "Kid"),
                         "Accept-Encoding": "gzip"},
                auto_decompress=False,
            )
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get("Content-Encoding"), "gzip")


class RateLimitUnitTests(unittest.TestCase):
    def test_rate_limit_eventually_blocks_on_flood(self):
        uid = 987654321
        _rate_buckets.pop((uid, "api"), None)
        try:
            self.assertTrue(_rate_limit_ok(uid, "api"), "первый запрос должен проходить")
            blocked = False
            for _ in range(5000):
                if not _rate_limit_ok(uid, "api"):
                    blocked = True
                    break
            self.assertTrue(blocked, "rate-limit должен сработать при потоке запросов")
        finally:
            _rate_buckets.pop((uid, "api"), None)


if __name__ == "__main__":
    unittest.main()
