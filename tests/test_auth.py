"""Юнит-тесты подписи авторизации (webapp/auth.py) — критичный security-код,
проверявшийся ранее только косвенно. Чистые функции, без сети/БД.
"""
import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from config import BOT_TOKEN
from webapp.auth import (
    _fallback_signature,
    make_fallback_auth_params,
    verify_fallback_auth,
    verify_init_data,
)


def _signed_init_data(params: dict) -> str:
    """Собирает валидную initData с корректной подписью (как у Telegram)."""
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "hash": h})


class FallbackAuthTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        params = make_fallback_auth_params(123, "Маша")
        res = verify_fallback_auth(urlencode(params))
        self.assertIsNotNone(res)
        self.assertEqual(res["user"]["id"], 123)
        self.assertEqual(res["user"]["first_name"], "Маша")

    def test_tampered_hash_rejected(self):
        params = make_fallback_auth_params(123, "Маша")
        params["fa_hash"] = "deadbeef"
        self.assertIsNone(verify_fallback_auth(urlencode(params)))

    def test_tampered_user_id_rejected(self):
        params = make_fallback_auth_params(123, "Маша")
        params["fa_user_id"] = "999"  # подпись больше не сходится
        self.assertIsNone(verify_fallback_auth(urlencode(params)))

    def test_expired_rejected(self):
        signed = {
            "fa_user_id": "123",
            "fa_first_name": "Маша",
            "fa_auth_date": str(int(time.time()) - 100000),
        }
        signed["fa_hash"] = _fallback_signature(signed)
        self.assertIsNone(verify_fallback_auth(urlencode(signed), max_age_seconds=3600))

    def test_missing_fields_rejected(self):
        self.assertIsNone(verify_fallback_auth(""))
        self.assertIsNone(verify_fallback_auth("fa_user_id=1"))  # нет hash/auth_date


class InitDataTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        params = {
            "auth_date": str(int(time.time())),
            "query_id": "abc",
            "user": json.dumps({"id": 7, "first_name": "Alex"}),
        }
        res = verify_init_data(_signed_init_data(params))
        self.assertIsNotNone(res)
        self.assertEqual(res["user"]["id"], 7)

    def test_wrong_hash_rejected(self):
        params = {"auth_date": str(int(time.time())), "user": "{}"}
        self.assertIsNone(verify_init_data(urlencode({**params, "hash": "00"})))

    def test_no_hash_rejected(self):
        self.assertIsNone(verify_init_data("auth_date=1&user=%7B%7D"))

    def test_expired_rejected(self):
        params = {
            "auth_date": str(int(time.time()) - 100000),
            "user": json.dumps({"id": 7}),
        }
        self.assertIsNone(verify_init_data(_signed_init_data(params), max_age_seconds=3600))

    def test_empty_rejected(self):
        self.assertIsNone(verify_init_data(""))


if __name__ == "__main__":
    unittest.main()
