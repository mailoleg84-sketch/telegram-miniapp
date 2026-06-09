"""Лимитирование запросов (вынесено из webapp/server.py).

In-memory счётчики per-user и per-IP (deque) по умолчанию. Если задан REDIS_URL —
async-точки `rate_limit_ok`/`photo_rate_limit_ok` используют общий Redis-лимит
(переживает рестарт, общий для инстансов); при ошибке Redis — фолбэк на in-memory.
"""
import logging
import time
from collections import defaultdict, deque

from config import AI_RATE_LIMIT_PER_MINUTE, API_RATE_LIMIT_PER_MINUTE

log = logging.getLogger(__name__)


AI_API_PATHS = {
    "/api/chat/send",
    "/api/audio/transcribe",
    "/api/audio/speech",
    "/api/voice/text-turn",
    "/api/voice/turn",
    "/api/vocab/image/generate",
    "/api/realtime/token",
    "/api/realtime/call",
}
_rate_buckets: dict[tuple[int, str], deque[float]] = defaultdict(deque)

# Публичный /vocabulary-photo не проходит auth-middleware, поэтому защищаем его
# отдельным IP-лимитом, чтобы нельзя было выжечь квоту Pixabay и забить диск.
_photo_ip_buckets: dict[str, deque[float]] = defaultdict(deque)
_PHOTO_IP_LIMIT = 30  # запросов в минуту с одного IP


def _photo_rate_limit_ok(ip: str) -> bool:
    now = time.monotonic()
    if len(_photo_ip_buckets) > 5000:
        for k in [k for k, b in _photo_ip_buckets.items() if not b or now - b[-1] > 60]:
            _photo_ip_buckets.pop(k, None)
    bucket = _photo_ip_buckets[ip]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= _PHOTO_IP_LIMIT:
        return False
    bucket.append(now)
    return True


def _rate_limit_key(path: str) -> str:
    return "ai" if path in AI_API_PATHS else "api"


def _rate_limit_for_key(key: str) -> int:
    return AI_RATE_LIMIT_PER_MINUTE if key == "ai" else API_RATE_LIMIT_PER_MINUTE


_rate_limit_calls = 0


def _sweep_rate_buckets(now: float) -> None:
    """Убирает корзины неактивных пользователей, чтобы словарь не рос вечно."""
    for bucket_key in [k for k, b in _rate_buckets.items() if not b or now - b[-1] > 60]:
        _rate_buckets.pop(bucket_key, None)


def _rate_limit_ok(user_id: int, key: str) -> bool:
    global _rate_limit_calls
    limit = _rate_limit_for_key(key)
    if limit <= 0:
        return True
    now = time.monotonic()
    _rate_limit_calls += 1
    if _rate_limit_calls % 500 == 0:
        _sweep_rate_buckets(now)
    bucket = _rate_buckets[(user_id, key)]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


# ── Async-точки для хендлеров: Redis при REDIS_URL, иначе in-memory (фолбэк) ────

async def rate_limit_ok(user_id: int, key: str) -> bool:
    """Лимит per-user. Redis (общий) если включён, иначе in-memory. Ошибка Redis
    не блокирует пользователя — фолбэк на in-memory."""
    from webapp import redis_store
    if redis_store.redis_enabled():
        try:
            return await redis_store.rate_limit_ok(user_id, key, _rate_limit_for_key(key))
        except Exception:  # noqa: BLE001
            log.warning("Redis rate-limit недоступен, фолбэк на in-memory", exc_info=True)
    return _rate_limit_ok(user_id, key)


async def photo_rate_limit_ok(ip: str) -> bool:
    """Лимит per-IP для публичного /vocabulary-photo. Redis если включён, иначе in-memory."""
    from webapp import redis_store
    if redis_store.redis_enabled():
        try:
            return await redis_store.rate_limit_ok(ip or "?", "photo", _PHOTO_IP_LIMIT)
        except Exception:  # noqa: BLE001
            log.warning("Redis photo-rate-limit недоступен, фолбэк на in-memory", exc_info=True)
    return _photo_rate_limit_ok(ip)
