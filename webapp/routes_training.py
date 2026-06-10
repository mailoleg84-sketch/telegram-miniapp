"""Тренировки «выбрать перевод» / «написать слово»: маршруты, выборка слова и
одноразовые токены попыток (вынесено из webapp/server.py, шаг 3d-2).

Зависимости направлены только «вниз» (config, database, redis_store, formatters,
word_payloads, http_utils) — модуль НЕ импортирует server.py, циклов нет.
server.py реэкспортирует имена: импорты и патчи в тестах работают как раньше
(вызовы redis_store.*/database.* идут через атрибуты модулей — patch цели те же).
"""
import logging
import random
import secrets
import time

from aiohttp import web

import database
from config import POINTS_CORRECT, POINTS_WRONG
from webapp import redis_store
from webapp.formatters import _normalized_age_group_for_user
from webapp.http_utils import _current_user_or_404, _safe_json
from webapp.word_payloads import _word_image_url

log = logging.getLogger(__name__)

# Одноразовые токены тренировочных заданий (анти-накрутка прогресса, QA H2).
# Сервер выдаёт токен в /next и гасит его в /answer; повторный ответ на то же
# задание не начисляет баллы и прогресс. Хранилище в памяти процесса — для
# одного инстанса этого достаточно, чтобы заблокировать replay.
_training_attempts: dict[str, dict] = {}
_TRAINING_ATTEMPT_TTL = 600  # секунд


def _prune_training_attempts() -> None:
    now = time.time()
    for token in [t for t, rec in _training_attempts.items() if rec["expires_at"] < now]:
        _training_attempts.pop(token, None)


async def _issue_training_attempt(user_id: int, word_id: int) -> str:
    """Выдаёт одноразовый токен. Бэкенд: Redis (если задан) → Postgres/Neon (по
    умолчанию, переживает рестарт) → in-memory (фолбэк при сбое)."""
    token = secrets.token_urlsafe(16)
    payload = {"user_id": user_id, "word_id": word_id}
    if redis_store.redis_enabled():
        try:
            await redis_store.issue_token(token, payload, _TRAINING_ATTEMPT_TTL)
            return token
        except Exception:  # noqa: BLE001
            log.warning("Redis issue_token недоступен, фолбэк дальше", exc_info=True)
    try:
        await database.issue_training_token(token, user_id, word_id, _TRAINING_ATTEMPT_TTL)
        return token
    except Exception:  # noqa: BLE001
        log.warning("Postgres issue_token недоступен, фолбэк на in-memory", exc_info=True)
    _prune_training_attempts()
    _training_attempts[token] = {**payload, "expires_at": time.time() + _TRAINING_ATTEMPT_TTL}
    return token


async def _consume_training_attempt(token: str, user_id: int, word_id: int) -> bool:
    """Гасит токен (одноразово). True только если валиден, не истёк, не использован.
    Бэкенд: Redis → Postgres/Neon → in-memory (тот же порядок, что у выдачи)."""
    token = str(token or "")
    if not token:
        return False
    if redis_store.redis_enabled():
        try:
            record = await redis_store.consume_token(token)
            if not record:
                return False
            return record.get("user_id") == user_id and record.get("word_id") == word_id
        except Exception:  # noqa: BLE001
            log.warning("Redis consume_token недоступен, фолбэк дальше", exc_info=True)
    try:
        return await database.consume_training_token(token, user_id, word_id)
    except Exception:  # noqa: BLE001
        log.warning("Postgres consume_token недоступен, фолбэк на in-memory", exc_info=True)
    _prune_training_attempts()
    record = _training_attempts.pop(token, None)
    if not record:
        return False
    if record["user_id"] != user_id or record["word_id"] != word_id:
        return False
    return record["expires_at"] >= time.time()


async def _select_training_word(user_id: int, body: dict, age_group: str):
    """Каскадная выборка слова для тренировок («выбрать перевод» / «написать
    слово»). Возвращает кортеж (word, error_response, focus, review_empty):
    при ошибке word=None и заполнен error_response (web.Response с тем же телом
    и статусом, что были инлайн в обработчиках).
    """
    focus = "review" if body.get("focus") == "review" else "all"
    exclude_ids = []
    for item in body.get("exclude_ids") or []:
        try:
            exclude_ids.append(int(item))
        except (TypeError, ValueError):
            continue

    word = None
    requested_word_id = body.get("word_id")
    if requested_word_id is not None:
        try:
            word = await database.get_word_by_id(int(requested_word_id))
        except (TypeError, ValueError):
            return None, web.json_response({"error": "bad payload"}, status=400), focus, False
        if not word:
            return None, web.json_response({"error": "word not found"}, status=404), focus, False

    if not word:
        word = await database.get_review_word(user_id, age_group=age_group, exclude_ids=exclude_ids) if focus == "review" else None
    review_empty = focus == "review" and not word
    if not word:
        word = await database.get_practice_word(user_id, age_group=age_group, exclude_ids=exclude_ids)
    if not word and exclude_ids:
        word = await database.get_review_word(user_id, age_group=age_group) if focus == "review" else None
        if not word:
            word = await database.get_practice_word(user_id, age_group=age_group)
    if not word:
        return None, web.json_response({"error": "Нет слов"}, status=500), focus, review_empty
    return word, None, focus, review_empty


async def api_choice_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    age_group = _normalized_age_group_for_user(user)
    word, error, focus, review_empty = await _select_training_word(user_id, body, age_group)
    if error:
        return error

    wrong = await database.get_random_words(3, exclude_id=word["id"], age_group=age_group)
    options = [{"id": word["id"], "translation": word["translation"]}]
    options += [{"id": w["id"], "translation": w["translation"]} for w in wrong]
    random.shuffle(options)

    return web.json_response({
        "word":    word["word"],
        "word_id": word["id"],
        "transcription": word["transcription"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "options": options,
        "focus": focus,
        "review_empty": review_empty,
        "attempt_id": await _issue_training_attempt(user_id, word["id"]),
    })


async def api_choice_answer(request: web.Request):
    body = await _safe_json(request)
    user_id = request["tg_user"]["id"]
    try:
        word_id     = int(body["word_id"])
        selected_id = int(body["selected_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    correct = selected_id == word_id
    focus = "review" if body.get("focus") == "review" else "all"
    counted = await _consume_training_attempt(body.get("attempt_id"), user_id, word_id)
    delta = (POINTS_CORRECT if correct else POINTS_WRONG) if counted else 0
    if counted:
        await database.update_points(user_id, delta)
        await database.update_progress(user_id, word_id, correct=correct)
        await database.add_training_attempt(user_id, "choice", focus, correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "word_id":     word_id,
        "correct":     correct,
        "counted":     counted,
        "word":        word["word"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "delta":       delta,
        "points":      user["points"],
    })


async def api_input_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    age_group = _normalized_age_group_for_user(user)
    word, error, focus, review_empty = await _select_training_word(user_id, body, age_group)
    if error:
        return error
    return web.json_response({
        "word_id":     word["id"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "focus": focus,
        "review_empty": review_empty,
        "attempt_id": await _issue_training_attempt(user_id, word["id"]),
    })


async def api_input_answer(request: web.Request):
    body = await _safe_json(request)
    user_id = request["tg_user"]["id"]
    try:
        word_id = int(body["word_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    answer = (body.get("answer") or "").strip().lower()

    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    correct = answer == word["word"].lower()
    focus = "review" if body.get("focus") == "review" else "all"
    counted = await _consume_training_attempt(body.get("attempt_id"), user_id, word_id)
    delta = (POINTS_CORRECT if correct else POINTS_WRONG) if counted else 0
    if counted:
        await database.update_points(user_id, delta)
        await database.update_progress(user_id, word_id, correct=correct)
        await database.add_training_attempt(user_id, "input", focus, correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "word_id":     word_id,
        "correct":     correct,
        "counted":     counted,
        "word":        word["word"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "image_url":   _word_image_url(word["word"], word["topic"] or "basic"),
        "delta":       delta,
        "points":      user["points"],
    })
