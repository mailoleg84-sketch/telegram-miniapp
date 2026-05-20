"""aiohttp-сервер: статика Mini App + JSON API."""
import logging
import random
from pathlib import Path

from aiohttp import web

import database
from config import AGE_GROUPS, POINTS_CORRECT, POINTS_WRONG, WEBAPP_HOST, WEBAPP_PORT
from webapp.auth import verify_init_data

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# ---------- Middleware ----------

@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Проверяет initData для всех /api/* эндпоинтов."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = verify_init_data(init_data)
    if not parsed or "user" not in parsed:
        return web.json_response({"error": "unauthorized"}, status=401)

    request["tg_user"] = parsed["user"]
    return await handler(request)


# ---------- Helpers ----------

def _word_dict(word) -> dict:
    if not word:
        return {}
    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "example": word["example"] or "",
    }


async def _safe_json(request: web.Request) -> dict:
    if request.body_exists:
        try:
            return await request.json()
        except Exception:
            return {}
    return {}


# ---------- API ----------

async def api_me(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user["id"]

    user = await database.get_user(user_id)
    if not user:
        return web.json_response({
            "registered": False,
            "tg_user": {
                "id": tg_user["id"],
                "first_name": tg_user.get("first_name", ""),
            },
            "age_groups": [{"value": v, "label": l} for l, v in AGE_GROUPS],
        })

    stats = await database.get_user_stats(user_id)
    age_label = next((l for l, v in AGE_GROUPS if v == user["age_group"]), user["age_group"])
    return web.json_response({
        "registered": True,
        "user": {
            "id":         user["user_id"],
            "name":       user["name"],
            "age_group":  user["age_group"],
            "age_label":  age_label,
            "points":     user["points"],
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong":   stats["total_wrong"],
        },
    })


async def api_register(request: web.Request):
    tg_user = request["tg_user"]
    body = await _safe_json(request)
    name = (body.get("name") or "").strip()
    age_group = body.get("age_group", "")

    if len(name) < 2 or len(name) > 30:
        return web.json_response({"error": "Имя должно быть от 2 до 30 символов"}, status=400)
    if age_group not in {v for _, v in AGE_GROUPS}:
        return web.json_response({"error": "Некорректная возрастная группа"}, status=400)

    await database.add_user(tg_user["id"], name, age_group)
    return web.json_response({"ok": True})


async def api_learn_next(request: web.Request):
    body = await _safe_json(request)
    exclude_id = body.get("current_id")
    word = await database.get_random_word(exclude_id=exclude_id)
    return web.json_response(_word_dict(word))


async def api_choice_next(request: web.Request):
    correct = await database.get_random_word()
    if not correct:
        return web.json_response({"error": "Нет слов"}, status=500)

    wrong = await database.get_random_words(3, exclude_id=correct["id"])
    options = [{"id": correct["id"], "translation": correct["translation"]}]
    options += [{"id": w["id"], "translation": w["translation"]} for w in wrong]
    random.shuffle(options)

    return web.json_response({
        "word":    correct["word"],
        "word_id": correct["id"],
        "options": options,
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
    delta = POINTS_CORRECT if correct else POINTS_WRONG
    await database.update_points(user_id, delta)
    await database.update_progress(user_id, word_id, correct=correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "correct":     correct,
        "word":        word["word"],
        "translation": word["translation"],
        "delta":       delta,
        "points":      user["points"],
    })


async def api_input_next(request: web.Request):
    word = await database.get_random_word()
    if not word:
        return web.json_response({"error": "Нет слов"}, status=500)
    return web.json_response({
        "word_id":     word["id"],
        "translation": word["translation"],
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
    delta = POINTS_CORRECT if correct else POINTS_WRONG
    await database.update_points(user_id, delta)
    await database.update_progress(user_id, word_id, correct=correct)

    user = await database.get_user(user_id)
    return web.json_response({
        "correct":     correct,
        "word":        word["word"],
        "translation": word["translation"],
        "delta":       delta,
        "points":      user["points"],
    })


# ---------- Static ----------

async def index_handler(request: web.Request):
    return web.FileResponse(STATIC_DIR / "index.html")


# ---------- App factory ----------

def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware])

    app.router.add_get("/",       index_handler)
    app.router.add_get("/api/me", api_me)
    app.router.add_post("/api/register",              api_register)
    app.router.add_post("/api/learn/next",            api_learn_next)
    app.router.add_post("/api/training/choice/next",  api_choice_next)
    app.router.add_post("/api/training/choice/answer", api_choice_answer)
    app.router.add_post("/api/training/input/next",   api_input_next)
    app.router.add_post("/api/training/input/answer", api_input_answer)
    app.router.add_static("/static", STATIC_DIR)

    return app


async def run_webapp() -> web.AppRunner:
    """Запускает aiohttp в текущем event loop. Возвращает runner для cleanup."""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    log.info("Mini App сервер слушает http://%s:%s", WEBAPP_HOST, WEBAPP_PORT)
    return runner
