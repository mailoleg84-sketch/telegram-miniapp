"""Опциональный Redis-бэкенд для rate-limit и одноразовых токенов тренировок.

Включается переменной ``REDIS_URL`` (например Upstash). Без неё всё работает на
in-memory структурах в процессе (как раньше) — это фолбэк по умолчанию.

Зачем: in-memory состояние теряется при рестарте Render и не разделяется между
инстансами. Redis делает rate-limit и токены общими и переживающими рестарт.

``redis`` импортируется лениво (только когда задан REDIS_URL), поэтому без Redis
зависимость не требуется. Любая ошибка Redis не валит запрос — вызывающий слой
делает фолбэк на in-memory.
"""
import json
import time

from config import REDIS_URL

_client = None


def redis_enabled() -> bool:
    return bool((REDIS_URL or "").strip())


async def _get_client():
    """Ленивый async-клиент Redis (кэшируется). Бросает наверх при ошибке."""
    global _client
    if _client is None:
        import redis.asyncio as redis  # ленивый импорт: нужен только при REDIS_URL
        _client = redis.from_url(
            REDIS_URL.strip(),
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )
    return _client


async def rate_limit_ok(identity, kind: str, limit: int) -> bool:
    """Фиксированное окно в 1 минуту через атомарный INCR. identity — user_id или IP."""
    if limit <= 0:
        return True
    client = await _get_client()
    bucket = int(time.time() // 60)
    key = f"rl:{kind}:{identity}:{bucket}"
    count = await client.incr(key)
    if count == 1:
        await client.expire(key, 60)
    return int(count) <= limit


async def issue_token(token: str, payload: dict, ttl: int) -> None:
    client = await _get_client()
    await client.set(f"tok:{token}", json.dumps(payload), ex=ttl)


async def consume_token(token: str) -> dict | None:
    """Атомарно забирает и удаляет токен (GETDEL) — гарантирует одноразовость."""
    client = await _get_client()
    raw = await client.getdel(f"tok:{token}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None
