"""PIN-код родительского раздела: хеширование, set/verify, лимит попыток.

БД-функции замоканы (прод-Neon не трогаем). Хендлеры вызываются напрямую с
фейковым request и замоканным _safe_json — как в tests/test_audio_cache.py.
"""
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from webapp import server


class _FakeReq:
    def __init__(self, user_id: int):
        self._d = {"tg_user": {"id": user_id}}

    def __getitem__(self, key):
        return self._d[key]


def _body(resp):
    return json.loads(resp.text)


class ParentPinHashTests(unittest.TestCase):
    def test_hash_deterministic_and_scoped(self):
        h = server._parent_pin_hash(1, "1234")
        self.assertEqual(h, server._parent_pin_hash(1, "1234"))   # детерминирован
        self.assertNotEqual(h, server._parent_pin_hash(1, "1235"))  # зависит от PIN
        self.assertNotEqual(h, server._parent_pin_hash(2, "1234"))  # зависит от user
        self.assertEqual(len(h), 64)  # sha256 hex
        self.assertNotIn("1234", h)   # открытый PIN не хранится

    def test_valid_pin(self):
        self.assertTrue(server._valid_pin("0000"))
        self.assertTrue(server._valid_pin("9999"))
        self.assertFalse(server._valid_pin("123"))
        self.assertFalse(server._valid_pin("12345"))
        self.assertFalse(server._valid_pin("abcd"))
        self.assertFalse(server._valid_pin(""))


class ParentPinSetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._pin_fail_attempts.clear()

    async def test_first_time_set_stores_hash(self):
        saved = {}

        async def _set(uid, pin_hash):
            saved["uid"], saved["hash"] = uid, pin_hash

        with patch("webapp.server._safe_json", AsyncMock(return_value={"pin": "4321"})), \
             patch("database.get_parent_pin_hash", AsyncMock(return_value=None)), \
             patch("database.set_parent_pin_hash", AsyncMock(side_effect=_set)):
            resp = await server.api_parent_pin_set(_FakeReq(7))
        self.assertEqual(resp.status, 200)
        self.assertTrue(_body(resp)["parent_pin_set"])
        self.assertEqual(saved["uid"], 7)
        self.assertEqual(saved["hash"], server._parent_pin_hash(7, "4321"))

    async def test_bad_pin_rejected(self):
        with patch("webapp.server._safe_json", AsyncMock(return_value={"pin": "12"})):
            resp = await server.api_parent_pin_set(_FakeReq(7))
        self.assertEqual(resp.status, 400)

    async def test_change_requires_correct_current(self):
        existing = server._parent_pin_hash(7, "1111")
        with patch("webapp.server._safe_json",
                   AsyncMock(return_value={"pin": "2222", "current_pin": "9999"})), \
             patch("database.get_parent_pin_hash", AsyncMock(return_value=existing)), \
             patch("database.set_parent_pin_hash", AsyncMock()) as setter:
            resp = await server.api_parent_pin_set(_FakeReq(7))
        self.assertEqual(resp.status, 403)
        setter.assert_not_awaited()

    async def test_change_pin_is_rate_limited(self):
        """Смена PIN тоже под лимитом — иначе перебор current_pin уходит мимо verify."""
        existing = server._parent_pin_hash(7, "1111")
        with patch("webapp.server._safe_json",
                   AsyncMock(return_value={"pin": "2222", "current_pin": "0000"})), \
             patch("database.get_parent_pin_hash", AsyncMock(return_value=existing)), \
             patch("database.set_parent_pin_hash", AsyncMock()):
            for _ in range(server._PIN_MAX_ATTEMPTS):
                resp = await server.api_parent_pin_set(_FakeReq(7))
                self.assertEqual(resp.status, 403)  # неверный текущий PIN
            locked = await server.api_parent_pin_set(_FakeReq(7))
        self.assertEqual(locked.status, 429)  # перебор смены PIN заблокирован


class ParentPinVerifyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        server._pin_fail_attempts.clear()

    async def _verify(self, user_id, pin, stored):
        with patch("webapp.server._safe_json", AsyncMock(return_value={"pin": pin})), \
             patch("database.get_parent_pin_hash", AsyncMock(return_value=stored)):
            return await server.api_parent_pin_verify(_FakeReq(user_id))

    async def test_correct_pin_ok(self):
        stored = server._parent_pin_hash(7, "1234")
        resp = await self._verify(7, "1234", stored)
        self.assertTrue(_body(resp)["ok"])

    async def test_not_set(self):
        resp = await self._verify(7, "1234", None)
        body = _body(resp)
        self.assertFalse(body["ok"])
        self.assertTrue(body["not_set"])

    async def test_malformed_pin_rejected_without_burning_attempts(self):
        """Пустой/мусорный ввод отклоняется 400 и НЕ тратит попытки (не залочит родителя)."""
        stored = server._parent_pin_hash(7, "1234")
        resp = await self._verify(7, "", stored)
        self.assertEqual(resp.status, 400)
        self.assertNotIn(7, server._pin_fail_attempts)

    async def test_wrong_pin_decrements_and_locks(self):
        stored = server._parent_pin_hash(7, "1234")
        # 5 неудач → на 6-й блокировка (429).
        for i in range(server._PIN_MAX_ATTEMPTS):
            resp = await self._verify(7, "0000", stored)
            self.assertEqual(resp.status, 200)
            self.assertFalse(_body(resp)["ok"])
        locked = await self._verify(7, "1234", stored)  # даже верный PIN — заблокирован
        self.assertEqual(locked.status, 429)
        self.assertTrue(_body(locked)["locked"])


class ParentPinWiringTests(unittest.TestCase):
    def test_frontend_uses_pin_gate_not_math(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
        server_py = (root / "webapp" / "server.py").read_text(encoding="utf-8")
        self.assertIn("renderParentPinEntry", app_js)
        self.assertIn("/api/parent/pin/verify", app_js)
        self.assertNotIn("реши пример", app_js)        # старый матем-гейт удалён
        self.assertNotIn("parent-gate-opt", app_js)
        self.assertIn('"/api/parent/pin/set"', server_py)
        self.assertIn('"/api/parent/pin/verify"', server_py)
        # При выходе родительский раздел снова под PIN (сброс parentZoneUnlocked).
        clear_start = app_js.index("function clearAccountLocalState()")
        clear_block = app_js[clear_start:clear_start + 900]
        self.assertIn("parentZoneUnlocked = false", clear_block)


if __name__ == "__main__":
    unittest.main()
