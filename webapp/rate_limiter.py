"""Лимитирование запросов (вынесено из webapp/server.py).

In-memory счётчики per-user и per-IP (deque). Состояние в памяти процесса:
при горизонтальном масштабировании переносится в Redis (см. план).
"""
import time
from collections import defaultdict, deque

from config import AI_RATE_LIMIT_PER_MINUTE, API_RATE_LIMIT_PER_MINUTE


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
