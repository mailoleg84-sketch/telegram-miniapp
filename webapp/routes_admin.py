"""Admin-маршруты и их гарды/сборщики (вынесено из webapp/server.py, шаг 3c).

Зависимости направлены только «вниз» (config, database, storage, openai_service,
formatters, payload_builders, http_utils) — модуль НЕ импортирует server.py,
поэтому циклических импортов нет. server.py импортирует отсюда хендлеры для
регистрации маршрутов и реэкспортирует имена для тестов.

`api_admin_user_detail` намеренно остаётся в server.py: его payload тянет
`_problem_word_dict` → `_word_dict` → визуализатор/кэш картинок (runtime-клей).
"""
from pathlib import Path

from aiohttp import web

import database
from config import (
    ADMIN_USER_IDS,
    AI_RATE_LIMIT_PER_MINUTE,
    API_RATE_LIMIT_PER_MINUTE,
    APP_VERSION,
    BOT_RUN_MODE,
    WEBAPP_URL,
)
from webapp import storage
from webapp.openai_service import openai_config_status
from webapp.formatters import _safe_int, _safe_float
from webapp.payload_builders import _admin_user_dict, _admin_failed_image_dict
from webapp.http_utils import _safe_json

# Для локального backend — каталог (Path); для S3/R2 — None (та же логика, что в
# server.py: значения производные от storage, не разделяемое состояние).
_GENERATED_VOCAB_DIR = getattr(storage.vocab_image_storage, "base_dir", None)
_AUDIO_CACHE_DIR = getattr(storage.word_audio_storage, "base_dir", None)


def _is_admin_user_id(user_id) -> bool:
    try:
        return int(user_id) in ADMIN_USER_IDS
    except (TypeError, ValueError):
        return False


def _is_admin_request(request: web.Request) -> bool:
    return _is_admin_user_id(request["tg_user"]["id"])


def _admin_forbidden_response() -> web.Response:
    return web.json_response({"error": "Доступ только для администратора"}, status=403)


def _file_cache_summary(path: Path) -> dict:
    files = [item for item in path.glob("*") if item.is_file()] if path.exists() else []
    return {
        "files": len(files),
        "size_mb": round(sum(item.stat().st_size for item in files) / 1024 / 1024, 2),
    }


def _admin_overview_payload(overview: dict) -> dict:
    users = overview.get("users")
    words = overview.get("words")
    learning = overview.get("learning")
    ai_today = overview.get("ai_today")
    ai_week = overview.get("ai_week")
    openai_status = openai_config_status()
    admin_ids_count = len(ADMIN_USER_IDS)
    failed_images = _safe_int(words, "failed_images")
    missing_images = _safe_int(words, "missing_images")
    health = []
    if admin_ids_count <= 0:
        health.append({
            "level": "critical",
            "title": "Администратор не настроен",
            "text": "Добавьте ADMIN_USER_IDS в Render, иначе панель не будет доступна владельцу.",
        })
    if not openai_status.get("configured"):
        health.append({
            "level": "critical",
            "title": "OpenAI не настроен",
            "text": "OPENAI_API_KEY отсутствует. Репетитор, озвучка и AI-картинки работать не будут.",
        })
    if failed_images > 0:
        health.append({
            "level": "warning",
            "title": "Есть ошибки генерации картинок",
            "text": f"{failed_images} слов имеют статус failed. После исправления billing/API сбросьте ошибки картинок.",
        })
    if missing_images > 0:
        health.append({
            "level": "info",
            "title": "Картинки ещё не сгенерированы",
            "text": f"{missing_images} слов ждут AI-картинки. Это нормально, если генерация идёт постепенно.",
        })
    if not health:
        health.append({
            "level": "ok",
            "title": "Система выглядит нормально",
            "text": "Критичных проблем в админской диагностике сейчас не видно.",
        })
    return {
        "health": health,
        "users": {
            "total": _safe_int(users, "total_users"),
            "new_today": _safe_int(users, "new_users_today"),
            "active_today": int(overview.get("active_today") or 0),
            "total_points": _safe_int(users, "total_points"),
        },
        "learning": {
            "completed_daily_lessons": _safe_int(learning, "completed_daily_lessons"),
            "completed_word_tests": _safe_int(learning, "completed_word_tests"),
            "completed_games": _safe_int(learning, "completed_games"),
            "training_attempts": _safe_int(learning, "training_attempts"),
            "learned_word_links": _safe_int(learning, "learned_word_links"),
        },
        "words": {
            "total": _safe_int(words, "total_words"),
            "generated_images": _safe_int(words, "generated_images"),
            "images_needing_review": _safe_int(words, "images_needing_review"),
            "failed_images": _safe_int(words, "failed_images"),
            "missing_images": _safe_int(words, "missing_images"),
            "semantic_review_words": _safe_int(words, "semantic_review_words"),
        },
        "ai_today": {
            "requests": _safe_int(ai_today, "requests"),
            "input_tokens": _safe_int(ai_today, "input_tokens"),
            "output_tokens": _safe_int(ai_today, "output_tokens"),
            "total_tokens": _safe_int(ai_today, "total_tokens"),
            "cost_usd": round(_safe_float(ai_today, "cost_usd"), 6),
        },
        "ai_week": {
            "requests": _safe_int(ai_week, "requests"),
            "total_tokens": _safe_int(ai_week, "total_tokens"),
            "cost_usd": round(_safe_float(ai_week, "cost_usd"), 6),
        },
        "cache": {
            "generated_images": _file_cache_summary(_GENERATED_VOCAB_DIR) if _GENERATED_VOCAB_DIR else {"backend": "r2"},
            "word_audio": _file_cache_summary(_AUDIO_CACHE_DIR) if _AUDIO_CACHE_DIR else {"backend": "r2"},
        },
        "config": {
            "app_version": APP_VERSION,
            "webapp_url": WEBAPP_URL,
            "bot_run_mode": BOT_RUN_MODE,
            "api_rate_limit_per_minute": API_RATE_LIMIT_PER_MINUTE,
            "ai_rate_limit_per_minute": AI_RATE_LIMIT_PER_MINUTE,
            "admin_ids_configured": admin_ids_count,
            "openai": openai_status,
        },
    }


async def api_admin_overview(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    overview = await database.get_admin_overview()
    failed_images = await database.get_admin_failed_image_words(limit=8)
    payload = _admin_overview_payload(overview)
    payload["failed_image_words"] = [_admin_failed_image_dict(row) for row in failed_images]
    return web.json_response(payload)


async def api_admin_users(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    search = (request.query.get("q") or "").strip()[:80]
    try:
        limit = int(request.query.get("limit") or 40)
    except (TypeError, ValueError):
        limit = 40
    rows = await database.get_admin_users(search=search, limit=limit)
    return web.json_response({
        "query": search,
        "users": [_admin_user_dict(row) for row in rows],
    })


async def api_admin_reset_user_results(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    body = await _safe_json(request)
    if body.get("confirm") != "reset_user_results":
        return web.json_response({"error": "Нужно подтвердить сброс результатов пользователя"}, status=400)
    try:
        target_user_id = int(body.get("user_id"))
    except (TypeError, ValueError):
        return web.json_response({"error": "Некорректный user_id"}, status=400)
    if not await database.user_exists(target_user_id):
        return web.json_response({"error": "Пользователь не найден"}, status=404)
    await database.reset_learning_results(target_user_id)
    return web.json_response({"ok": True, "user_id": target_user_id})


async def api_admin_reset_image_failures(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    body = await _safe_json(request)
    if body.get("confirm") != "reset_image_failures":
        return web.json_response({"error": "Нужно подтвердить сброс статусов картинок"}, status=400)
    updated = await database.reset_failed_generated_images()
    return web.json_response({"ok": True, "updated": updated})
