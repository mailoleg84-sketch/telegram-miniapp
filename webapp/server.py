"""aiohttp-сервер: статика Mini App + JSON API."""
import base64
from collections import defaultdict, deque
import logging
import random
import time
from pathlib import Path

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database
from config import (
    AGE_GROUPS,
    AI_RATE_LIMIT_PER_MINUTE,
    API_RATE_LIMIT_PER_MINUTE,
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
from webapp.auth import verify_fallback_auth, verify_init_data
from webapp.openai_service import chat_reply, create_realtime_call, create_realtime_client_secret, public_openai_error, synthesize_speech, transcribe_audio

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SDP_BYTES = 512 * 1024
PUBLIC_API_PATHS = {"/api/me", "/api/register"}
AI_API_PATHS = {
    "/api/chat/send",
    "/api/audio/transcribe",
    "/api/audio/speech",
    "/api/voice/text-turn",
    "/api/voice/turn",
    "/api/realtime/token",
    "/api/realtime/call",
}
_rate_buckets: dict[tuple[int, str], deque[float]] = defaultdict(deque)


def _rate_limit_key(path: str) -> str:
    return "ai" if path in AI_API_PATHS else "api"


def _rate_limit_for_key(key: str) -> int:
    return AI_RATE_LIMIT_PER_MINUTE if key == "ai" else API_RATE_LIMIT_PER_MINUTE


def _rate_limit_ok(user_id: int, key: str) -> bool:
    limit = _rate_limit_for_key(key)
    if limit <= 0:
        return True
    now = time.monotonic()
    bucket = _rate_buckets[(user_id, key)]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


# ---------- Middleware ----------

@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Проверяет initData для всех /api/* эндпоинтов."""
    if not request.path.startswith("/api/"):
        return await handler(request)

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    parsed = verify_init_data(init_data)
    if not parsed:
        parsed = verify_fallback_auth(request.headers.get("X-App-Fallback-Auth", ""))
    if not parsed or "user" not in parsed:
        return web.json_response({"error": "unauthorized"}, status=401)

    request["tg_user"] = parsed["user"]
    user_id = int(parsed["user"]["id"])
    key = _rate_limit_key(request.path)
    if not _rate_limit_ok(user_id, key):
        return web.json_response({
            "error": "Слишком много запросов. Подожди минуту и попробуй снова.",
        }, status=429)
    if request.path not in PUBLIC_API_PATHS and not await database.user_exists(user_id):
        return web.json_response({"error": "Сначала нужно зарегистрироваться"}, status=403)
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


async def _read_audio_upload(request: web.Request) -> tuple[bytes, str, str]:
    try:
        reader = await request.multipart()
        field = await reader.next()
    except Exception as exc:
        raise web.HTTPBadRequest(text="Нужно отправить аудиофайл") from exc

    if not field or field.name != "audio":
        raise web.HTTPBadRequest(text="Поле audio не найдено")

    chunks = []
    total = 0
    while True:
        chunk = await field.read_chunk(size=64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise web.HTTPRequestEntityTooLarge(
                max_size=MAX_AUDIO_BYTES,
                actual_size=total,
                text="Голосовое сообщение слишком большое",
            )
        chunks.append(chunk)

    audio = b"".join(chunks)
    if not audio:
        raise web.HTTPBadRequest(text="Пустое голосовое сообщение")

    return (
        audio,
        field.filename or "voice.webm",
        field.headers.get("Content-Type", "audio/webm"),
    )


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


def _level_for_user(user) -> str:
    goal = user["goal"] if user else ""
    age_group = user["age_group"] if user else ""
    if goal in {"exams", "travel"} or age_group == "14_18":
        return "elementary"
    if age_group in {"5_7", "8_10"} or goal == "first_steps":
        return "beginner"
    return "beginner+"


def _style_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    if age_group in {"5_7", "8_10"}:
        return "игровой, очень доброжелательный, с простыми фразами и мини-играми"
    if age_group == "14_18":
        return "спокойный, дружелюбный, с диалогами и реальными ситуациями"
    return "дружелюбный, короткими репликами, с понятными примерами"


def _topics_for_user(user) -> str:
    goal = user["goal"] if user else ""
    age_group = user["age_group"] if user else ""
    if goal == "travel":
        return "путешествия, аэропорт, кафе, покупки, знакомство, карта города"
    if goal == "exams":
        return "школа, хобби, планы, короткие диалоги, экзаменационные темы без стресса"
    if goal == "speaking":
        return "игры, друзья, спорт, музыка, фильмы, хобби, повседневные диалоги"
    if age_group in {"5_7", "8_10"}:
        return "животные, цвета, еда, игрушки, игры, школа, сказочные истории"
    return "школа, игры, спорт, путешествия, хобби, истории, повседневные ситуации"


def _normalized_age_group_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    try:
        child_age = int(user["child_age"] or 0) if user else 0
    except (TypeError, ValueError):
        child_age = 0
    if age_group in {"5_7", "8_10", "11_13", "14_18"}:
        return age_group
    if 5 <= child_age <= 7:
        return "5_7"
    if 8 <= child_age <= 10:
        return "8_10"
    if 11 <= child_age <= 13:
        return "11_13"
    if 14 <= child_age <= 18:
        return "14_18"
    if age_group in {"under_12", "under12", "under_10"}:
        return "8_10"
    return "8_10"


def _prompt_context_for_user(user) -> dict:
    return {
        "age": str(user["child_age"] or _age_label(user["age_group"])) if user else "не указан",
        "age_group": _normalized_age_group_for_user(user),
        "level": _level_for_user(user),
        "goal": _goal_label(user["goal"]) if user else "разговорная практика",
        "style": _style_for_user(user),
        "topics": _topics_for_user(user),
    }


def _voice_topic_bank(user) -> list[str]:
    age_group = user["age_group"] if user else ""
    goal = user["goal"] if user else ""
    if goal == "travel":
        return [
            "airport adventure", "hotel check-in", "cafe order", "city map",
            "souvenir shop", "beach day", "train station", "lost backpack",
            "photo walk", "weather talk", "ice cream kiosk", "museum quest",
            "passport helper", "bus stop", "theme park", "family trip",
            "restaurant mistake", "ask for directions",
        ]
    if goal == "exams":
        return [
            "school day", "favorite hobby", "weekend plans", "short interview",
            "picture description", "study routine", "sports club", "my room",
            "healthy food", "future job", "friendship", "small presentation",
            "compare two pictures", "tell a mini story", "opinion practice",
            "exam calm-down", "daily routine challenge", "question cards",
        ]
    if age_group in {"5_7", "8_10"}:
        return [
            "magic shop", "space picnic", "robot friend", "treasure map",
            "funny cafe", "toy store", "school bag", "secret door",
            "superhero training", "rainbow colors", "little chef", "sports day",
            "pet doctor", "birthday party", "snowy park", "music game",
            "dragon library", "pirate bakery", "dino museum", "jungle camera",
            "monster picnic", "art studio", "weather machine", "lost teddy",
            "train of words", "moon playground", "detective game", "tiny theater",
        ]
    if age_group == "11_13":
        return [
            "school project", "gaming club", "sports practice", "music playlist",
            "movie scene", "travel vlog", "cafe dialogue", "new classmate",
            "weekend plan", "pet story", "shopping challenge", "mystery quest",
            "YouTube plan", "comic book idea", "science fair", "escape room",
            "football commentary", "birthday planning", "school club pitch",
            "phone call practice",
        ]
    return [
        "real conversation", "travel problem", "school debate", "job interview mini",
        "movie discussion", "music and hobbies", "daily routine", "exam warm-up",
        "ordering food", "city directions", "online safety", "future plans",
        "small talk practice", "opinion challenge", "presentation opener",
        "friendly disagreement", "study abroad scene", "interview with a blogger",
    ]


def _choose_voice_topics(user, messages: list[dict], count: int = 3) -> list[str]:
    bank = _voice_topic_bank(user)
    recent_text = " ".join(m["content"] for m in messages[-10:]).lower()
    fresh = [topic for topic in bank if topic.lower() not in recent_text]
    if len(fresh) < count:
        fresh = bank[:]
    random.shuffle(fresh)
    return fresh[:count]


def _voice_lesson_focus(messages: list[dict]) -> str:
    recent = [
        " ".join(str(message.get("content") or "").split())
        for message in messages[-6:]
        if str(message.get("content") or "").strip()
    ]
    if not recent:
        return "урок только начинается"
    return (
        "Текущая линия урока — последние реплики: "
        + " | ".join(recent[-4:])
        + ". Продолжай эту тему и мини-сцену, пока ребенок сам не попросит сменить тему."
    )


def _voice_prompt_context(user, messages: list[dict]) -> dict:
    topics = _choose_voice_topics(user, messages)
    lesson_focus = _voice_lesson_focus(messages)
    has_history = any(str(message.get("content") or "").strip() for message in messages)
    recent_user_messages = [m["content"] for m in messages if m["role"] == "user"][-3:]
    recent_assistant_messages = [m["content"] for m in messages if m["role"] == "assistant"][-3:]
    return {
        "lesson_focus": lesson_focus,
        "topic_suggestions": (
            "не меняй текущую тему; запасные темы только если ребенок явно просит сменить тему: "
            + ", ".join(topics)
            if has_history else ", ".join(topics)
        ),
        "avoid_topics": (
            "Не меняй тему по таймеру и не начинай новый урок сам. "
            "Продолжай текущую линию урока 8-10 реплик или до явной просьбы ребенка сменить тему. "
            "Не перечисляй новые темы, если ребенок уже находится в мини-сцене."
        ),
        "recent_user_messages": " | ".join(recent_user_messages) or "пока нет",
        "recent_assistant_messages": " | ".join(recent_assistant_messages) or "пока нет",
        "activity_menu": (
            "роль: продавец/покупатель, мини-квест, угадай слово, естественный вопрос, "
            "выбор из двух вариантов, вопрос про день ребенка, короткая смешная сценка, "
            "мини-история на 2 реплики, возвращение к слову из прошлой реплики"
        ),
        "lesson_loop": (
            "Сначала живо отреагируй на смысл реплики ребенка. Затем обязательно добавь маленькую учебную пользу: "
            "одну английскую фразу вроде I want..., I like..., Can I have...?, одно слово, мягкое исправление "
            "или выбор из двух вариантов. Не требуй повторения каждый раз; иногда задай естественный вопрос "
            "или продолжи сцену. Держи одну тему урока, пока ребенок сам не сменит ее. Через несколько реплик верни одно старое слово."
        ),
        "conversation_plan": (
            "1) Сначала понять настоящий запрос ребенка: вопрос, просьба, выбор темы, усталость или ошибка. "
            "2) Ответить по сути на этот запрос, не игнорировать его ради плана урока. "
            "3) Всегда связать ответ с короткой учебной пользой: фразой, словом, исправлением, выбором или мини-практикой. "
            "4) Продолжить текущую мини-сцену 8-10 ходов, если ребенок не просит сменить тему. "
            "5) Каждые 3-4 реплики можно менять активность внутри той же темы: мини-диалог, угадай слово, роль, вопрос, исправление. "
            "6) Если ребенок отвечает коротко, упростить и дать выбор из двух вариантов. "
            "7) Если ребенок спрашивает по-русски, ответить по-русски и дать одну маленькую английскую фразу."
        ),
    }


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


async def api_results_reset(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    if body.get("confirm") != "reset_results":
        return web.json_response({"error": "Нужно подтвердить сброс результатов"}, status=400)

    await database.reset_learning_results(user_id)
    user = await database.get_user(user_id)
    stats = await database.get_user_stats(user_id)
    return web.json_response({
        "ok": True,
        "user": {
            "points": user["points"] if user else 0,
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong": stats["total_wrong"],
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
        log.error("No vocabulary words available for user=%s age_group=%s", user_id, age_group)
        return web.json_response({
            "error": "Пока не удалось загрузить слова. Попробуй открыть профиль и проверить возраст ребенка.",
        }, status=500)

    session = await database.create_vocabulary_session(
        user_id=user_id,
        age_group=age_group if age_group in WORDS_PER_AGE_GROUP else "8_10",
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
    mode = "voice" if body.get("mode") == "voice" else "chat"
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
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = mode
    if mode == "voice":
        prompt_context.update(_voice_prompt_context(user, history))
    reply = await chat_reply(history, user_name, age_label, prompt_context)

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
        audio, filename, content_type = await _read_audio_upload(request)
    except web.HTTPRequestEntityTooLarge as e:
        return web.json_response({"error": e.text}, status=413)
    except web.HTTPBadRequest as e:
        return web.json_response({"error": e.text}, status=400)

    try:
        text = await transcribe_audio(
            audio,
            filename=filename,
            content_type=content_type,
        )
    except Exception as e:
        log.exception("Audio transcription failed")
        return web.json_response({"error": f"Не удалось распознать голос. {public_openai_error(e)}"}, status=502)

    return web.json_response({"text": text})


async def api_audio_speech(request: web.Request):
    body = await _safe_json(request)
    text = (body.get("text") or "").strip()
    mode = "voice" if body.get("mode") == "voice" else "chat"
    if not text:
        return web.json_response({"error": "Нет текста для озвучки"}, status=400)
    if len(text) > 1200:
        text = text[:1200]

    try:
        audio = await synthesize_speech(text, mode=mode)
    except Exception as e:
        log.exception("Speech synthesis failed")
        return web.json_response({"error": f"Не удалось озвучить ответ. {public_openai_error(e)}"}, status=502)

    return web.Response(
        body=audio,
        content_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        },
    )


async def _voice_text_turn_payload(user_id: int, text: str) -> dict:
    stats = await database.get_ai_usage_today(user_id)
    user = await database.get_user(user_id)
    user_name = user["name"] if user else "друг"

    await database.add_message(user_id, "user", text)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context.update(_voice_prompt_context(user, history))

    reply = await chat_reply(history, user_name, age_label, prompt_context)
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

    audio_b64 = ""
    audio_error = ""
    if not reply.text.startswith("Ошибка:") and not reply.text.startswith("⚠️"):
        try:
            speech = await synthesize_speech(reply.text, mode="voice")
            audio_b64 = base64.b64encode(speech).decode("ascii")
        except Exception as e:
            log.exception("Hybrid voice speech synthesis failed")
            audio_error = public_openai_error(e)

    return {
        "text": text,
        "reply": reply.text,
        "audio_base64": audio_b64,
        "audio_content_type": "audio/mpeg" if audio_b64 else "",
        "audio_error": audio_error,
        "usage": _chat_usage_payload(stats),
    }


async def api_voice_text_turn(request: web.Request):
    """Stable hybrid turn when speech was already transcribed by Realtime."""
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    text = " ".join((body.get("message") or body.get("text") or "").split())
    if not text:
        return web.json_response({"error": "empty message"}, status=400)
    if len(text) > 1000:
        text = text[:1000]

    try:
        payload = await _voice_text_turn_payload(user_id, text)
    except Exception as e:
        log.exception("Hybrid voice text turn failed")
        return web.json_response({"error": public_openai_error(e)}, status=502)
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def api_voice_turn(request: web.Request):
    """Stable hybrid voice turn: transcribe, reply, and synthesize in one request."""
    user_id = request["tg_user"]["id"]
    try:
        audio, filename, content_type = await _read_audio_upload(request)
    except web.HTTPRequestEntityTooLarge as e:
        return web.json_response({"error": e.text}, status=413)
    except web.HTTPBadRequest as e:
        return web.json_response({"error": e.text}, status=400)

    try:
        text = await transcribe_audio(audio, filename=filename, content_type=content_type)
    except Exception as e:
        log.exception("Hybrid voice transcription failed")
        return web.json_response({"error": f"Не удалось распознать голос. {public_openai_error(e)}"}, status=502)

    text = " ".join(text.split())
    if not text:
        return web.json_response({"error": "Не расслышал голос"}, status=400)
    if len(text) > 1000:
        text = text[:1000]

    try:
        payload = await _voice_text_turn_payload(user_id, text)
    except Exception as e:
        log.exception("Hybrid voice turn failed")
        return web.json_response({"error": public_openai_error(e)}, status=502)
    return web.json_response(payload, headers={"Cache-Control": "no-store"})


async def api_realtime_call(request: web.Request):
    user_id = request["tg_user"]["id"]
    raw_body = await request.read()
    sdp_offer = raw_body.decode("utf-8", errors="replace").strip()
    log.info(
        "Realtime SDP: content_type=%s body_len=%d sdp_starts=%s",
        request.content_type, len(raw_body), repr(sdp_offer[:40]) if sdp_offer else "EMPTY",
    )
    if not sdp_offer or len(raw_body) > MAX_SDP_BYTES:
        return web.json_response({"error": f"Некорректный SDP: len={len(raw_body)}, starts={repr(sdp_offer[:30])}"}, status=400)

    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _realtime_prompt_context(user, history)

    try:
        answer_sdp = await create_realtime_call(
            sdp_offer=sdp_offer,
            user_id=user_id,
            user_name=user["name"] if user else "друг",
            age_label=age_label,
            prompt_context=prompt_context,
        )
    except Exception as e:
        log.exception("Realtime call setup failed: %s", e)
        return web.json_response({"error": public_openai_error(e)}, status=502)

    return web.Response(
        text=answer_sdp,
        content_type="application/sdp",
        headers={"Cache-Control": "no-store"},
    )


def _realtime_prompt_context(user, history: list[dict]) -> dict:
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context["age_group"] = _normalized_age_group_for_user(user) if user else "8_10"
    prompt_context.update(_voice_prompt_context(user, history))
    return prompt_context


async def api_realtime_token(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _realtime_prompt_context(user, history)

    try:
        token = await create_realtime_client_secret(
            user_id=user_id,
            user_name=user["name"] if user else "друг",
            age_label=age_label,
            prompt_context=prompt_context,
        )
    except Exception as e:
        log.exception("Realtime token setup failed: %s", e)
        return web.json_response({"error": public_openai_error(e)}, status=502)

    return web.json_response(token, headers={"Cache-Control": "no-store"})


async def api_realtime_log(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    role = "assistant" if body.get("role") == "assistant" else "user"
    content = " ".join(str(body.get("content") or "").split())
    if not content:
        return web.json_response({"ok": True})
    if len(content) > 1000:
        content = content[:1000]
    await database.add_message(user_id, role, content)
    return web.json_response({"ok": True})


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

def create_app(
    bot=None,
    dispatcher=None,
    webhook_path: str | None = None,
    webhook_secret: str | None = None,
) -> web.Application:
    app = web.Application(middlewares=[auth_middleware], client_max_size=MAX_AUDIO_BYTES + 1024 * 1024)

    app.router.add_get("/",        index_handler)
    app.router.add_get("/api/me",  api_me)
    app.router.add_get("/api/leaderboard",              api_leaderboard)
    app.router.add_get("/api/parent/report",            api_parent_report)
    app.router.add_post("/api/results/reset",           api_results_reset)
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
    app.router.add_post("/api/voice/text-turn",        api_voice_text_turn)
    app.router.add_post("/api/voice/turn",             api_voice_turn)
    app.router.add_post("/api/realtime/token",         api_realtime_token)
    app.router.add_post("/api/realtime/call",          api_realtime_call)
    app.router.add_post("/api/realtime/log",           api_realtime_log)
    app.router.add_post("/api/chat/reset",             api_chat_reset)

    if bot is not None and dispatcher is not None and webhook_path:
        SimpleRequestHandler(
            dispatcher=dispatcher,
            bot=bot,
            secret_token=webhook_secret or None,
        ).register(app, path=webhook_path)
        setup_application(app, dispatcher, bot=bot)

    app.router.add_static("/static", STATIC_DIR)

    return app


async def run_webapp(
    bot=None,
    dispatcher=None,
    webhook_path: str | None = None,
    webhook_secret: str | None = None,
) -> web.AppRunner:
    """Запускает aiohttp в текущем event loop. Возвращает runner для cleanup."""
    app = create_app(
        bot=bot,
        dispatcher=dispatcher,
        webhook_path=webhook_path,
        webhook_secret=webhook_secret,
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    log.info("Mini App сервер слушает http://%s:%s", WEBAPP_HOST, WEBAPP_PORT)
    return runner
