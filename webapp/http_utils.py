"""Мелкие HTTP-помощники для обработчиков (aiohttp), без бизнес-логики.

Вынесено из webapp/server.py (шаг рефакторинга 3c), чтобы модули маршрутов
(например, webapp/routes_admin.py) не зависели от server.py. server.py
реэкспортирует имена — существующие вызовы и патчи в тестах работают как раньше.
"""
import logging

from aiohttp import web

import database

log = logging.getLogger(__name__)


async def _safe_json(request: web.Request) -> dict:
    if request.body_exists:
        try:
            return await request.json()
        except Exception:
            log.warning("Не удалось разобрать JSON тела запроса на %s %s",
                        request.method, request.path)
            return {}
    return {}


async def _current_user_or_404(request: web.Request):
    user = await database.get_user(request["tg_user"]["id"])
    if not user:
        raise web.HTTPBadRequest(text="user is not registered")
    return user
