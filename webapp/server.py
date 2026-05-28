"""aiohttp-сервер: статика Mini App + JSON API."""
import logging
import random
from pathlib import Path

from aiohttp import web

import database
from config import (
    AGE_GROUPS,
    APP_VERSION,
    CHAT_HISTORY_LIMIT,
    DAILY_LESSON_REWARD_POINTS,
    DAILY_LESSON_STEPS,
    LEARNING_GOALS,
    POINTS_CORRECT,
    POINTS_WRONG,
    WORDS_PER_AGE_GROUP,
    WEBAPP_HOST,
    WEBAPP_PORT,
)
from webapp.auth import verify_init_data
from webapp.openai_service import chat_reply, synthesize_speech, transcribe_audio

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
MAX_AUDIO_BYTES = 8 * 1024 * 1024


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
        "topic": word["topic"] or "basic",
        "age_group": word["age_group"] or "",
    }


async def _safe_json(request: web.Request) -> dict:
    if request.body_exists:
        try:
            return await request.json()
        except Exception:
            return {}
    return {}


def _chat_usage_payload(stats) -> dict:
    used = int(stats["requests"] if stats else 0)
    return {
        "used_today": used,
        "daily_limit": None,
        "remaining_today": None,
        "unlimited": True,
        "input_tokens_today": int(stats["input_tokens"] if stats else 0),
        "output_tokens_today": int(stats["output_tokens"] if stats else 0),
        "total_tokens_today": int(stats["total_tokens"] if stats else 0),
        "cost_usd_today": round(float(stats["cost_usd"] if stats else 0), 6),
    }


def _daily_lesson_payload(status, reward_points: int = 0, points: int | None = None) -> dict:
    completed_steps = int(status["completed_steps"] if status else 0)
    return {
        "lesson_date": status["lesson_date"] if status else "",
        "completed_steps": completed_steps,
        "total_steps": DAILY_LESSON_STEPS,
        "completed": bool(status["completed"] if status else False),
        "rewarded": bool(status["rewarded"] if status else False),
        "reward_points": reward_points,
        "points": points,
    }


def _age_label(age_group: str) -> str:
    return next((label for label, value in AGE_GROUPS if value == age_group), age_group)


def _goal_label(goal: str | None) -> str:
    return next((label for label, value in LEARNING_GOALS if value == goal), goal or "")


async def _current_user_or_404(request: web.Request):
    user = await database.get_user(request["tg_user"]["id"])
    if not user:
        raise web.HTTPBadRequest(text="user is not registered")
    return user


async def _build_vocab_question(word, age_group: str) -> dict:
    wrong = await database.get_word_options(word["id"], age_group, count=3)
    options = [{"id": word["id"], "translation": word["translation"]}]
    options += [{"id": item["id"], "translation": item["translation"]} for item in wrong]
    random.shuffle(options)
    return {
        "word_id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "example": word["example"] or "",
        "type": "picture" if age_group == "5_7" else "translation",
        "prompt": "Выбери перевод",
        "options": options,
    }


# ---------- API: профиль и регистрация ----------

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
            "goals": [{"value": v, "label": l} for l, v in LEARNING_GOALS],
        })

    stats = await database.get_user_stats(user_id)
    return web.json_response({
        "registered": True,
        "user": {
            "id":         user["user_id"],
            "child_name": user["name"],
            "parent_name": user["parent_name"] or "",
            "child_age": user["child_age"],
            "age_group":  user["age_group"],
            "age_label":  _age_label(user["age_group"]),
            "goal": user["goal"] or "",
            "goal_label": _goal_label(user["goal"]),
            "points":     user["points"],
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong":   stats["total_wrong"],
        },
    })


async def api_leaderboard(request: web.Request):
    user_id = request["tg_user"]["id"]
    rows = await database.get_leaderboard(limit=10)

    leaders = []
    for index, row in enumerate(rows, start=1):
        age_label = next((l for l, v in AGE_GROUPS if v == row["age_group"]), row["age_group"])
        leaders.append({
            "rank": index,
            "id": row["user_id"],
            "name": row["name"],
            "age_label": age_label,
            "points": row["points"],
            "is_me": row["user_id"] == user_id,
        })

    return web.json_response({"leaders": leaders})


async def api_register(request: web.Request):
    tg_user = request["tg_user"]
    body = await _safe_json(request)
    name = (body.get("child_name") or body.get("name") or "").strip()
    parent_name = (body.get("parent_name") or "").strip()
    age_group = body.get("age_group", "")
    goal = body.get("goal", "")
    try:
        child_age = int(body.get("child_age") or 0)
    except (TypeError, ValueError):
        child_age = 0

    if len(name) < 2 or len(name) > 30:
        return web.json_response({"error": "Имя ребенка должно быть от 2 до 30 символов"}, status=400)
    if parent_name and (len(parent_name) < 2 or len(parent_name) > 30):
        return web.json_response({"error": "Имя родителя должно быть от 2 до 30 символов"}, status=400)
    if age_group not in {v for _, v in AGE_GROUPS}:
        return web.json_response({"error": "Некорректная возрастная группа"}, status=400)
    if goal and goal not in {v for _, v in LEARNING_GOALS}:
        return web.json_response({"error": "Некорректная цель обучения"}, status=400)
    if child_age and (child_age < 5 or child_age > 18):
        return web.json_response({"error": "Возраст ребенка должен быть от 5 до 18 лет"}, status=400)

    await database.add_user(
        tg_user["id"],
        name,
        age_group,
        parent_name=parent_name or tg_user.get("first_name", ""),
        child_age=child_age or None,
        goal=goal or None,
    )
    return web.json_response({"ok": True})


async def api_parent_report(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    report = await database.get_parent_report(user_id)
    stats = await database.get_user_stats(user_id)
    return web.json_response({
        "child": {
            "name": user["name"],
            "age_group": user["age_group"],
            "age_label": _age_label(user["age_group"]),
            "goal_label": _goal_label(user["goal"]),
            "points": user["points"],
        },
        "report": {
            "words_learned": int((report or stats)["words_learned"] or 0),
            "total_correct": int((report or stats)["total_correct"] or 0),
            "total_wrong": int((report or stats)["total_wrong"] or 0),
            "completed_lessons": int(report["completed_lessons"] if report else 0),
            "completed_word_tests": int(report["completed_word_tests"] if report else 0),
            "avg_word_test_score": int(report["avg_word_test_score"] if report else 0),
        },
    })


# ---------- API: ежедневный урок ----------

async def api_daily_status(request: web.Request):
    user_id = request["tg_user"]["id"]
    status = await database.get_daily_lesson_status(user_id)
    return web.json_response(_daily_lesson_payload(status))


async def api_daily_progress(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        completed_steps = int(body.get("completed_steps", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad payload"}, status=400)

    status = await database.update_daily_lesson_progress(
        user_id,
        completed_steps=completed_steps,
        total_steps=DAILY_LESSON_STEPS,
    )
    reward_points = 0
    points = None

    if status["completed"]:
        rewarded = await database.claim_daily_lesson_reward(user_id)
        if rewarded:
            reward_points = DAILY_LESSON_REWARD_POINTS
            await database.update_points(user_id, DAILY_LESSON_REWARD_POINTS)
            user = await database.get_user(user_id)
            points = user["points"] if user else None
            status = await database.get_daily_lesson_status(user_id)

    return web.json_response(_daily_lesson_payload(status, reward_points, points))


# ---------- API: обучение ----------

async def api_learn_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    exclude_id = body.get("current_id")
    word = await database.get_practice_word(user_id, exclude_id=exclude_id)
    return web.json_response(_word_dict(word))


async def api_vocab_start(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    topic = (body.get("topic") or "").strip() or None
    age_group = user["age_group"]
    count = WORDS_PER_AGE_GROUP.get(age_group, 6)
    words = await database.get_words_for_age(age_group, count=count, topic=topic)
    if not words:
        return web.json_response({"error": "Нет слов для этой возрастной группы"}, status=500)

    session = await database.create_vocabulary_session(
        user_id=user_id,
        age_group=age_group,
        topic=topic,
        word_ids=[w["id"] for w in words],
    )
    return web.json_response({
        "session_id": session["id"],
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "words": [_word_dict(w) for w in words],
    })


async def api_vocab_quiz(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_vocabulary_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "session not found"}, status=404)
    words = await database.get_words_by_ids(list(session["word_ids"]))
    questions = [await _build_vocab_question(word, session["age_group"]) for word in words]
    return web.json_response({
        "session_id": session_id,
        "questions": questions,
    })


async def api_vocab_finish(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
        answers = body["answers"]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_vocabulary_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "session not found"}, status=404)
    if session["completed"]:
        return web.json_response({"error": "Этот тест уже завершен"}, status=400)

    words = await database.get_words_by_ids(list(session["word_ids"]))
    words_by_id = {w["id"]: w for w in words}
    results = []
    correct_count = 0
    wrong_count = 0
    total_delta = 0

    for raw in answers:
        try:
            word_id = int(raw.get("word_id"))
            selected_id = int(raw.get("selected_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        word = words_by_id.get(word_id)
        if not word:
            continue
        correct = selected_id == word_id
        if correct:
            correct_count += 1
            total_delta += POINTS_CORRECT
        else:
            wrong_count += 1
            total_delta += POINTS_WRONG
        await database.update_progress(user_id, word_id, correct=correct)
        results.append({
            "word_id": word_id,
            "word": word["word"],
            "translation": word["translation"],
            "correct": correct,
        })

    await database.finish_vocabulary_session(session_id, user_id, correct_count, wrong_count)
    await database.update_points(user_id, total_delta)
    user = await database.get_user(user_id)
    total = correct_count + wrong_count
    return web.json_response({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "total": total,
        "score": round(correct_count / total * 100) if total else 0,
        "delta": total_delta,
        "points": user["points"] if user else 0,
        "results": results,
    })


async def api_choice_next(request: web.Request):
    user_id = request["tg_user"]["id"]
    correct = await database.get_practice_word(user_id)
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
    user_id = request["tg_user"]["id"]
    word = await database.get_practice_word(user_id)
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


# ---------- API: ИИ-репетитор ----------

async def api_chat_history(request: web.Request):
    user_id = request["tg_user"]["id"]
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT * 2)
    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    stats = await database.get_ai_usage_today(user_id)
    return web.json_response({
        "messages": messages,
        "usage": _chat_usage_payload(stats),
    })


async def api_chat_send(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    text = (body.get("message") or "").strip()
    if not text:
        return web.json_response({"error": "empty message"}, status=400)
    if len(text) > 1000:
        text = text[:1000]

    stats = await database.get_ai_usage_today(user_id)

    user = await database.get_user(user_id)
    user_name = user["name"] if user else "друг"

    # Сохраняем сообщение пользователя
    await database.add_message(user_id, "user", text)

    # Берём последние сообщения как контекст для модели
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    reply = await chat_reply(history, user_name, age_label)

    await database.add_message(user_id, "assistant", reply.text)
    if reply.total_tokens > 0:
        await database.add_ai_usage(
            user_id=user_id,
            model=reply.model,
            input_tokens=reply.input_tokens,
            output_tokens=reply.output_tokens,
            total_tokens=reply.total_tokens,
            cost_usd=reply.cost_usd,
        )
        stats = await database.get_ai_usage_today(user_id)

    return web.json_response({
        "reply": reply.text,
        "usage": _chat_usage_payload(stats),
    })


async def api_audio_transcribe(request: web.Request):
    try:
        reader = await request.multipart()
        field = await reader.next()
    except Exception:
        return web.json_response({"error": "Нужно отправить аудиофайл"}, status=400)

    if not field or field.name != "audio":
        return web.json_response({"error": "Поле audio не найдено"}, status=400)

    chunks = []
    total = 0
    while True:
        chunk = await field.read_chunk(size=64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            return web.json_response({"error": "Голосовое сообщение слишком большое"}, status=413)
        chunks.append(chunk)

    audio = b"".join(chunks)
    if not audio:
        return web.json_response({"error": "Пустое голосовое сообщение"}, status=400)

    try:
        text = await transcribe_audio(
            audio,
            filename=field.filename or "voice.webm",
            content_type=field.headers.get("Content-Type", "audio/webm"),
        )
    except Exception as e:
        log.exception("Audio transcription failed")
        return web.json_response({"error": f"Не удалось распознать голос: {e}"}, status=502)

    return web.json_response({"text": text})


async def api_audio_speech(request: web.Request):
    body = await _safe_json(request)
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "Нет текста для озвучки"}, status=400)
    if len(text) > 1200:
        text = text[:1200]

    try:
        audio = await synthesize_speech(text)
    except Exception as e:
        log.exception("Speech synthesis failed")
        return web.json_response({"error": f"Не удалось озвучить ответ: {e}"}, status=502)

    return web.Response(
        body=audio,
        content_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
    )


async def api_chat_reset(request: web.Request):
    user_id = request["tg_user"]["id"]
    await database.clear_conversation(user_id)
    return web.json_response({"ok": True})


# ---------- Static ----------

async def index_handler(request: web.Request):
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    text = text.replace("__APP_VERSION__", APP_VERSION)
    return web.Response(
        text=text,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


# ---------- App factory ----------

def create_app() -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=MAX_AUDIO_BYTES + 1024 * 1024)

    app.router.add_get("/",        index_handler)
    app.router.add_get("/api/me",  api_me)
    app.router.add_get("/api/leaderboard",              api_leaderboard)
    app.router.add_get("/api/parent/report",            api_parent_report)
    app.router.add_get("/api/daily/status",             api_daily_status)
    app.router.add_post("/api/daily/progress",          api_daily_progress)
    app.router.add_post("/api/register",               api_register)
    app.router.add_post("/api/learn/next",             api_learn_next)
    app.router.add_post("/api/vocab/start",            api_vocab_start)
    app.router.add_post("/api/vocab/quiz",             api_vocab_quiz)
    app.router.add_post("/api/vocab/finish",           api_vocab_finish)
    app.router.add_post("/api/training/choice/next",   api_choice_next)
    app.router.add_post("/api/training/choice/answer", api_choice_answer)
    app.router.add_post("/api/training/input/next",    api_input_next)
    app.router.add_post("/api/training/input/answer",  api_input_answer)
    app.router.add_get("/api/chat/history",            api_chat_history)
    app.router.add_post("/api/chat/send",              api_chat_send)
    app.router.add_post("/api/audio/transcribe",       api_audio_transcribe)
    app.router.add_post("/api/audio/speech",           api_audio_speech)
    app.router.add_post("/api/chat/reset",             api_chat_reset)
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
