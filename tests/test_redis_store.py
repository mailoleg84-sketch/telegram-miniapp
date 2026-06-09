"""Тесты опционального Redis-бэкенда (redis_store) и async-диспетчера лимитов.

Реальный redis не нужен: клиент мокается. Проверяем включение по REDIS_URL,
fixed-window лимит, одноразовый GETDEL-токен и фолбэк на in-memory при ошибке.
"""
import unittest
from unittest.mock import AsyncMock, patch

from webapp import redis_store
from webapp import rate_limiter


class FakeRedis:
    def __init__(self, incr_val=1, getdel_val=None):
        self._incr = incr_val
        self._getdel = getdel_val
        self.expire_called = False
        self.last_set = None

    async def incr(self, key):
        return self._incr

    async def expire(self, key, ttl):
        self.expire_called = True

    async def getdel(self, key):
        return self._getdel

    async def set(self, key, val, ex=None):
        self.last_set = (key, val, ex)


class RedisEnabledTests(unittest.TestCase):
    def test_enabled_by_url(self):
        with patch("webapp.redis_store.REDIS_URL", ""):
            self.assertFalse(redis_store.redis_enabled())
        with patch("webapp.redis_store.REDIS_URL", "rediss://x"):
            self.assertTrue(redis_store.redis_enabled())


class RedisRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_under_limit_ok(self):
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=FakeRedis(incr_val=1))):
            self.assertTrue(await redis_store.rate_limit_ok(7, "api", 10))

    async def test_over_limit_blocks(self):
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=FakeRedis(incr_val=11))):
            self.assertFalse(await redis_store.rate_limit_ok(7, "api", 10))

    async def test_zero_limit_is_unlimited(self):
        # limit<=0 -> True без обращения к клиенту
        self.assertTrue(await redis_store.rate_limit_ok(7, "api", 0))


class RedisTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_consume_returns_payload(self):
        fake = FakeRedis(getdel_val='{"user_id": 7, "word_id": 42}')
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=fake)):
            out = await redis_store.consume_token("t")
        self.assertEqual(out, {"user_id": 7, "word_id": 42})

    async def test_consume_missing_returns_none(self):
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=FakeRedis(getdel_val=None))):
            self.assertIsNone(await redis_store.consume_token("t"))

    async def test_consume_bad_json_returns_none(self):
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=FakeRedis(getdel_val="not-json"))):
            self.assertIsNone(await redis_store.consume_token("t"))

    async def test_issue_sets_with_ttl(self):
        fake = FakeRedis()
        with patch("webapp.redis_store._get_client", AsyncMock(return_value=fake)):
            await redis_store.issue_token("t", {"user_id": 7}, 600)
        self.assertIsNotNone(fake.last_set)
        self.assertEqual(fake.last_set[0], "tok:t")
        self.assertEqual(fake.last_set[2], 600)


class DispatchFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_inmemory_when_redis_disabled(self):
        uid = 555000111
        rate_limiter._rate_buckets.pop((uid, "api"), None)
        with patch("webapp.redis_store.redis_enabled", return_value=False):
            self.assertTrue(await rate_limiter.rate_limit_ok(uid, "api"))  # первый проходит
        rate_limiter._rate_buckets.pop((uid, "api"), None)

    async def test_falls_back_to_inmemory_on_redis_error(self):
        uid = 555000222
        rate_limiter._rate_buckets.pop((uid, "api"), None)
        with patch("webapp.redis_store.redis_enabled", return_value=True), \
             patch("webapp.redis_store.rate_limit_ok", AsyncMock(side_effect=RuntimeError("down"))):
            result = await rate_limiter.rate_limit_ok(uid, "api")
        self.assertIsInstance(result, bool)
        self.assertTrue(result)  # in-memory: первый проходит
        rate_limiter._rate_buckets.pop((uid, "api"), None)


if __name__ == "__main__":
    unittest.main()
