"""Интеграционные тесты aiohttp-приложения: авторизация, заголовки, статика,
rate-limit. Не требуют реальной БД — где нужно, database мокается.
"""
import unittest
from unittest.mock import AsyncMock, patch
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
