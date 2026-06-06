"""Проверка подписи initData от Telegram WebApp."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from config import BOT_TOKEN


def _fallback_signature(params: dict[str, str]) -> str:
    data = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    return hmac.new(BOT_TOKEN.encode(), data.encode(), hashlib.sha256).hexdigest()


def make_fallback_auth_params(user_id: int, first_name: str = "") -> dict[str, str]:
    """Создает короткую подписанную авторизацию для случаев, когда Telegram не отдал initData."""
    params = {
        "fa_user_id": str(user_id),
        "fa_first_name": (first_name or "")[:64],
        "fa_auth_date": str(int(time.time())),
    }
    params["fa_hash"] = _fallback_signature(params)
    return params


def verify_fallback_auth(auth_data: str, max_age_seconds: int = 86400) -> dict | None:
    if not auth_data:
        return None

    try:
        parsed = dict(parse_qsl(auth_data.lstrip("?"), strict_parsing=False))
    except ValueError:
        return None

    received_hash = parsed.get("fa_hash")
    signed = {
        "fa_user_id": parsed.get("fa_user_id", ""),
        "fa_first_name": parsed.get("fa_first_name", ""),
        "fa_auth_date": parsed.get("fa_auth_date", ""),
    }
    if not signed["fa_user_id"] or not signed["fa_auth_date"] or not received_hash:
        return None
    if not hmac.compare_digest(_fallback_signature(signed), received_hash):
        return None

    try:
        if time.time() - int(signed["fa_auth_date"]) > max_age_seconds:
            return None
        user_id = int(signed["fa_user_id"])
    except ValueError:
        return None

    return {
        "user": {
            "id": user_id,
            "first_name": signed["fa_first_name"],
        }
    }


def verify_init_data(init_data: str, max_age_seconds: int = 86400) -> dict | None:
    """Возвращает распарсенный dict (с распакованным user) если подпись валидна, иначе None."""
    if not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    auth_date = parsed.get("auth_date")
    if auth_date:
        try:
            if time.time() - int(auth_date) > max_age_seconds:
                return None
        except ValueError:
            return None

    if "user" in parsed:
        try:
            parsed["user"] = json.loads(parsed["user"])
        except json.JSONDecodeError:
            return None

    return parsed
