"""aiohttp-сервер: статика Mini App + JSON API."""
import asyncio
import hashlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database
from config import (
    AGE_GROUPS,
    APP_VERSION,
    DAILY_LESSON_REWARD_POINTS,
    DAILY_LESSON_STEPS,
    ENGLISH_LEVELS,
    GAME_PERFECT_BONUS_POINTS,
    GAME_POINTS_CORRECT,
    LEARNING_GOALS,
    POINTS_CORRECT,
    POINTS_WRONG,
    WORDS_PER_AGE_GROUP,
    WEBAPP_HOST,
    WEBAPP_PORT,
    OPENAI_IMAGE_MODEL,
    VOCAB_FREE_PHOTOS,
    PIXABAY_API_KEY,
    OPENAI_IMAGE_COST_PER_CALL,
)
from webapp.auth import verify_fallback_auth, verify_init_data
from webapp.openai_service import (
    generate_vocabulary_image,
    public_openai_error,
)
from webapp.vocabulary_visualizer import (
    build_vocabulary_visual,
    vocabulary_image_url,
    is_sensitive_word,
)
from webapp.free_images import fetch_word_illustration
from webapp import storage
# Чистка локальных кэшей вынесена в webapp/storage.py (шаг 3e-1). Реэкспорт —
# вызовы внутри server.py и возможные импорты в тестах не меняются.
from webapp.storage import _evict_cache_dir

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
# Каталоги кэшей берём из слоя хранилища (webapp/storage.py). По умолчанию это
# <static>/generated (как раньше); через переменную окружения CACHE_ROOT можно
# вынести их на постоянный диск Render, чтобы кэши переживали деплой.
# Для локального backend — каталог (Path); для S3/R2 — None (нет локального пути).
GENERATED_VOCAB_DIR = getattr(storage.vocab_image_storage, "base_dir", None)
VOCAB_PHOTO_CACHE_DIR = getattr(storage.vocab_photo_storage, "base_dir", None)
VOCAB_PHOTO_CACHE_MAX_FILES = int(os.getenv("VOCAB_PHOTO_CACHE_MAX_FILES", "800"))
# Кэши на эфемерном диске Render не должны расти бесконечно (QA-аудит).
VOCAB_IMAGE_CACHE_MAX_FILES = int(os.getenv("VOCAB_IMAGE_CACHE_MAX_FILES", "4000"))
PUBLIC_API_PATHS = {"/api/me", "/api/register"}
# Лимитирование вынесено в webapp/rate_limiter.py. Реэкспорт только нужного:
# тело server.py зовёт rate_limit_ok/_rate_limit_key/photo_rate_limit_ok,
# тесты импортируют _rate_limit_ok/_rate_buckets через webapp.server.
from webapp.rate_limiter import (
    _rate_buckets,
    _rate_limit_key,
    _rate_limit_ok,
    photo_rate_limit_ok,
    rate_limit_ok,
)


# SVG-рендер вынесен в webapp/svg_renderer.py (чистые функции построения SVG).
from webapp.svg_renderer import (
    _word_image_svg,
    _vocabulary_visual_svg,
)
# Чистые форматтеры/метки/логика уровня вынесены в webapp/formatters.py
# (шаг рефакторинга 3a). Реэкспорт — чтобы существующие импорты и вызовы внутри
# server.py продолжали работать без изменений.
from webapp.formatters import (
    _record_value,
    _safe_int,
    _date_text,
    _age_label,
    _goal_label,
    _level_label,
    _level_for_user,
    _level_from_score,
    _level_result_message,
    _level_questions_for_age,
    _public_level_question,
    _path_step,
    _game_title,
    _age_group_from_age,
    _normalized_age_group_for_user,
)
# Чистые сборщики payload'ов вынесены в webapp/payload_builders.py (шаг 3b).
# Реэкспорт — чтобы вызовы внутри server.py и импорты в тестах не менялись.
from webapp.payload_builders import (
    _chat_usage_payload,
    _daily_lesson_payload,
    _activity_event_dict,
    _parent_recommendations,
    _motivation_badge,
)
# HTTP-помощники и admin-маршруты вынесены (шаг 3c). Направление зависимостей —
# только server -> routes_admin (модуль не импортирует server, цикла нет).
from webapp.http_utils import _safe_json, _current_user_or_404
from webapp.routes_admin import (
    _is_admin_user_id,
    _is_admin_request,
    _admin_forbidden_response,
    api_admin_overview,
    api_admin_users,
    api_admin_reset_user_results,
    api_admin_reset_image_failures,
)
# Тренировки (токены попыток, выборка слова, 4 хендлера) вынесены в
# webapp/routes_training.py (шаг 3d-2). Реэкспорт — хендлеры для create_app,
# выборка/токены — для тестов, что импортируют их через webapp.server.
from webapp.routes_training import (
    _issue_training_attempt,
    _consume_training_attempt,
    _select_training_word,
    api_choice_next,
    api_choice_answer,
    api_input_next,
    api_input_answer,
)
# ИИ-репетитор (чат, озвучка/распознавание, голосовой ход, Realtime) вынесен в
# webapp/routes_chat_voice.py (шаг 3e-3). Реэкспорт — хендлеры регистрирует
# create_app; MAX_AUDIO_BYTES/_record_ai_cost зовёт тело server.py; кэш-имя
# озвучки и голосовой ход импортируют тесты через webapp.server. Контекст
# промптов/состояние урока (webapp/voice_context.py) сюда НЕ реэкспортируем —
# его потребляет routes_chat_voice напрямую, server им не пользуется.
from webapp.routes_chat_voice import (
    MAX_AUDIO_BYTES,
    _record_ai_cost,
    _word_audio_cache_name,
    _voice_text_turn_payload,
    api_chat_history,
    api_chat_send,
    api_audio_transcribe,
    api_audio_speech,
    api_voice_text_turn,
    api_voice_turn,
    api_realtime_call,
    api_realtime_token,
    api_realtime_log,
    api_chat_reset,
)
# Word-payload слой (словари слова + URL-ы картинок) вынесен в
# webapp/word_payloads.py (шаг 3d-1). Реэкспорт — то, что зовёт тело server.py
# или импортируют тесты (через webapp.server).
from webapp.word_payloads import (
    _word_image_url,
    _vocab_card_image_url,
    _generated_vocab_url_exists,
    _generated_vocab_extension,
    _generated_vocab_static_url,
    _word_dict,
    _dictionary_word_dict,
    _problem_word_dict,
)


def _vocab_photo_cache_name(word: str) -> str:
    """Имя файла кэша фото (sha1 от нормализованного слова, без расширения).
    Каталог/префикс и `.none`-маркер добавляются поверх; работает и для диска, и
    для S3/R2 через storage.vocab_photo_storage."""
    raw = " ".join(str(word or "").split()).lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _sniff_image_type(body: bytes) -> str:
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    # Намеренно НЕ распознаём SVG: отдавать image/svg+xml с этого эндпоинта —
    # вектор XSS. Любой не-растровый ответ трактуем как jpeg (и не пройдёт <img>).
    return "image/jpeg"


async def vocabulary_photo_handler(request: web.Request):
    """Public: a free child-safe Pixabay illustration for a word (cached bytes),
    or 302 -> the SVG scene when there is none. The client also falls back to SVG on error."""
    raw = (request.query.get("w") or "").strip().lower()
    word = "".join(ch for ch in raw if ch.isalpha() or ch in " '-").strip()[:40].strip()
    topic = " ".join((request.query.get("t") or "").split()).lower()[:32]

    def svg_fallback():
        safe = word or "word"
        visual = build_vocabulary_visual(word=safe, translation="", topic=topic)
        url = visual.get("image_url") or vocabulary_image_url(safe, "no_good_visual", topic)
        return web.HTTPFound(location=url)

    def serve(body: bytes, cache_state: str):
        return web.Response(body=body, content_type=_sniff_image_type(body), headers={
            "Cache-Control": "public, max-age=604800",
            "X-Vocab-Photo": cache_state,
            "X-Content-Type-Options": "nosniff",
        })

    if not VOCAB_FREE_PHOTOS or not word or is_sensitive_word(word):
        return svg_fallback()

    if not await photo_rate_limit_ok(request.remote or ""):
        return web.Response(status=429, text="Too Many Requests")

    cache_name = _vocab_photo_cache_name(word)
    none_name = cache_name + ".none"
    try:
        cached = await storage.vocab_photo_storage.read(cache_name)
    except Exception:  # noqa: BLE001 — нет объекта/файла -> промах кэша
        cached = None
    if cached:
        return serve(cached, "hit")
    try:
        has_none = await storage.vocab_photo_storage.exists(none_name)
    except Exception:  # noqa: BLE001
        has_none = False
    if has_none:
        return svg_fallback()

    try:
        result = await fetch_word_illustration(word, topic)
    except Exception:
        log.exception("Vocab illustration fetch crashed")
        result = None

    if not result:
        # Запоминаем «картинки нет» только если реально искали (ключ задан) —
        # иначе после установки PIXABAY_API_KEY слова застряли бы на SVG.
        if PIXABAY_API_KEY:
            try:
                await storage.vocab_photo_storage.write(none_name, b"1")
                if VOCAB_PHOTO_CACHE_DIR is not None:  # eviction только локально (S3 — lifecycle)
                    _evict_cache_dir(VOCAB_PHOTO_CACHE_DIR, VOCAB_PHOTO_CACHE_MAX_FILES)
            except Exception:  # noqa: BLE001
                pass
        return svg_fallback()

    body, _ctype = result
    try:
        await storage.vocab_photo_storage.write(cache_name, body)
        if VOCAB_PHOTO_CACHE_DIR is not None:  # eviction только локально (S3 — lifecycle)
            _evict_cache_dir(VOCAB_PHOTO_CACHE_DIR, VOCAB_PHOTO_CACHE_MAX_FILES)
    except Exception:  # noqa: BLE001
        log.exception("Failed to store vocab photo cache")
    return serve(body, "miss")


# (SVG-билдеры вынесены в webapp/svg_renderer.py — см. импорт выше.)


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
    if not await rate_limit_ok(user_id, key):
        return web.json_response({
            "error": "Слишком много запросов. Подожди минуту и попробуй снова.",
        }, status=429)
    if request.path not in PUBLIC_API_PATHS and not await database.user_exists(user_id):
        return web.json_response({"error": "Сначала нужно зарегистрироваться"}, status=403)
    return await handler(request)


# ---------- Helpers ----------

# `_admin_user_detail_payload` и `api_admin_user_detail` остаются здесь (а не в
# routes_admin): payload тянет `_problem_word_dict` -> `_word_dict` ->
# визуализатор и кэш сгенерированных картинок (runtime-клей server.py).
def _admin_user_detail_payload(user, stats, report, dictionary_summary, problem_words, history, ai_today, streak) -> dict:
    level = _level_for_user(user)
    age_group = _normalized_age_group_for_user(user)
    stats_payload = {
        "words_learned": _safe_int(stats, "words_learned"),
        "total_correct": _safe_int(stats, "total_correct"),
        "total_wrong": _safe_int(stats, "total_wrong"),
    }
    total_answers = stats_payload["total_correct"] + stats_payload["total_wrong"]
    report_payload = {
        "completed_lessons": _safe_int(report, "completed_lessons"),
        "completed_word_tests": _safe_int(report, "completed_word_tests"),
        "avg_word_test_score": _safe_int(report, "avg_word_test_score"),
        "completed_games": _safe_int(report, "completed_games"),
        "avg_game_score": _safe_int(report, "avg_game_score"),
    }
    return {
        "user": {
            "id": _safe_int(user, "user_id"),
            "child_name": _record_value(user, "name", ""),
            "parent_name": _record_value(user, "parent_name", "") or "",
            "child_age": _record_value(user, "child_age", None),
            "age_group": age_group,
            "age_label": _age_label(age_group),
            "goal_label": _goal_label(_record_value(user, "goal", "")),
            "level": level,
            "level_label": _level_label(level),
            "level_test_score": _record_value(user, "level_test_score", None),
            "level_test_completed": bool(_record_value(user, "level_test_completed_at")),
            "points": _safe_int(user, "points"),
            "registered_at": _date_text(_record_value(user, "registered_at")),
        },
        "stats": {
            **stats_payload,
            "accuracy": round(stats_payload["total_correct"] / total_answers * 100) if total_answers else 0,
        },
        "report": report_payload,
        "dictionary": {
            "total_words": _safe_int(dictionary_summary, "total_words"),
            "mastered_words": _safe_int(dictionary_summary, "mastered_words"),
            "review_words": _safe_int(dictionary_summary, "review_words"),
        },
        "streak": streak or {},
        "problem_words": [_problem_word_dict(row) for row in problem_words],
        "history": [_activity_event_dict(row) for row in history],
        "ai_today": _chat_usage_payload(ai_today),
    }


def _blank_word_in_example(word: str, example: str) -> str:
    """Заменяет первое вхождение целевого слова в примере на пропуск.

    Возвращает '' если слова нет в примере (тогда формат «пропуск» не предлагается).
    """
    word = (word or "").strip()
    example = (example or "").strip()
    if not word or not example:
        return ""
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    if not pattern.search(example):
        return ""
    return pattern.sub("_____", example, count=1)


def _pick_distractors(pool, correct_id, count: int = 3) -> list:
    """Выбирает до `count` случайных неправильных вариантов из готового пула слов.

    Пул заранее загружается ОДНИМ запросом на весь квиз/игру (анти-N+1), а
    варианты для каждого вопроса набираются в памяти — со случайностью на
    вопрос (random.sample) и исключением правильного ответа по id.
    """
    correct_id = int(correct_id)
    eligible = [item for item in (pool or []) if int(item["id"]) != correct_id]
    if len(eligible) <= count:
        return list(eligible)
    return random.sample(eligible, count)


async def _build_vocab_question(word, age_group: str, index: int = 0, pool=None) -> dict:
    """Строит вопрос теста по словам.

    Тип чередуется по позиции слова, чтобы тест не был однообразным:
    - translation: показываем слово -> выбрать перевод;
    - word: показываем перевод -> выбрать английское слово;
    - gap: показываем пример с пропуском -> выбрать пропущенное слово.
    Во всех типах правильный вариант — это тот, чей id == word_id, поэтому
    логика подсчёта на /api/vocab/finish не меняется.
    """
    example = (word["example"] or "").strip()
    gap_text = _blank_word_in_example(word["word"], example)

    qtypes = ["translation", "word"]
    if gap_text and age_group != "5_7":
        qtypes.append("gap")
    qtype = qtypes[index % len(qtypes)]

    if qtype == "translation":
        wrong = _pick_distractors(pool, word["id"], 3)
        if len(wrong) < 3:
            wrong = await database.get_word_options(word["id"], age_group, count=3)
        options = [{"id": word["id"], "label": word["translation"]}]
        options += [{"id": item["id"], "label": item["translation"]} for item in wrong]
        prompt = "Выбери перевод"
    else:
        wrong = _pick_distractors(pool, word["id"], 3)
        if len(wrong) < 3:
            wrong = await database.get_random_words(3, exclude_id=word["id"], age_group=age_group)
        options = [{"id": word["id"], "label": word["word"]}]
        options += [{"id": item["id"], "label": item["word"]} for item in wrong]
        prompt = "Вставь пропущенное слово" if qtype == "gap" else "Выбери английское слово"

    random.shuffle(options)

    # Перевод показываем как ВОПРОС только для типов word/gap (там ответ —
    # английское слово). Для типа translation перевод — это ответ, поэтому в
    # payload он не попадает.
    prompt_translation = word["translation"]
    if qtype == "translation":
        return {
            "word_id": word["id"],
            "type": "translation",
            "word": word["word"],
            "transcription": word["transcription"] or "",
            "translation": "",
            "example": "",
            "gap_text": "",
            "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
            "prompt": prompt,
            "options": options,
        }
    # Ответ — английское слово: прячем слово, транскрипцию, картинку и полный
    # пример (gap_text уже с пропуском).
    return {
        "word_id": word["id"],
        "type": qtype,
        "word": "",
        "transcription": "",
        "translation": prompt_translation,
        "example": "",
        "gap_text": gap_text if qtype == "gap" else "",
        "image_url": "",
        "prompt": prompt,
        "options": options,
    }


async def _build_word_hunt_round(word, age_group: str, pool=None) -> dict:
    wrong = _pick_distractors(pool, word["id"], 3)
    if len(wrong) < 3:
        wrong = await database.get_random_words(3, exclude_id=word["id"], age_group=age_group)
    options = [{"id": word["id"], "word": word["word"]}]
    options += [{"id": item["id"], "word": item["word"]} for item in wrong]
    random.shuffle(options)
    return {
        "word_id": word["id"],
        "translation": word["translation"],
        "transcription": word["transcription"] or "",
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "prompt": f"Поймай английское слово для: {word['translation']}",
        "options": options,
    }


def _learning_path_payload(user, daily_status, stats, dictionary_summary, report) -> dict:
    level_done = bool(_record_value(user, "level_test_completed_at"))
    daily_steps = int(_record_value(daily_status, "completed_steps", 0) or 0)
    daily_done = bool(_record_value(daily_status, "completed", False))
    words_learned = int(_record_value(stats, "words_learned", 0) or 0)
    review_words = int(_record_value(dictionary_summary, "review_words", 0) or 0)

    if not level_done:
        next_action = "level"
        next_title = "Сначала узнаем уровень"
        next_text = "Короткий тест поможет давать задания не слишком легкие и не слишком сложные."
    elif not daily_done:
        next_action = "daily"
        # Неразрывные пробелы: «шаг N из M» не должен ломаться переносом (UX).
        next_title = f"Продолжить урок: шаг {min(daily_steps + 1, DAILY_LESSON_STEPS)} из {DAILY_LESSON_STEPS}"
        next_text = "Сегодняшний план: слова, мини-тест, фраза и награда."
    elif words_learned == 0:
        next_action = "vocab"
        next_title = "Добавить первые слова"
        next_text = "Небольшой набор слов даст основу для игр и устной практики."
    elif review_words > 0:
        next_action = "review"
        next_title = f"Повторить {review_words} слов"
        next_text = "Сегодня подошёл интервал повторения — короткая тренировка освежит эти слова."
    else:
        next_action = "learn"
        next_title = "Выбрать следующую тренировку"
        next_text = "Дневной план готов. Можно взять новые слова или повторить сложные."

    steps = [
        _path_step(
            "level",
            "Уровень",
            _level_label(_level_for_user(user)),
            "level",
            "done" if level_done else "current",
        ),
        _path_step(
            "daily",
            "Урок дня",
            f"{daily_steps}/{DAILY_LESSON_STEPS} шагов",
            "daily",
            "done" if daily_done else ("current" if level_done else "ready"),
        ),
        _path_step(
            "vocab",
            "Слова",
            f"{words_learned} в словаре",
            "vocab",
            "done" if words_learned > 0 else ("current" if daily_done else "ready"),
        ),
        _path_step(
            "review",
            "Повторение",
            f"{review_words} готовы сегодня",
            "review",
            "current" if review_words > 0 else ("done" if words_learned > 0 else "ready"),
        ),
    ]
    done_count = sum(1 for step in steps if step["status"] == "done")
    return {
        "title": "Дневной план",
        "next_action": next_action,
        "next_title": next_title,
        "next_text": next_text,
        "review_words": review_words,  # SRS: сколько слов готово к повторению сегодня (для нуджа на фронте)
        "progress_percent": round(done_count / len(steps) * 100),
        "steps": steps,
    }


def _motivation_payload(user, stats, dictionary_summary, report, streak) -> dict:
    words_learned = int(_record_value(stats, "words_learned", 0) or 0)
    total_correct = int(_record_value(stats, "total_correct", 0) or 0)
    total_wrong = int(_record_value(stats, "total_wrong", 0) or 0)
    review_words = int(_record_value(dictionary_summary, "review_words", 0) or 0)
    completed_lessons = int(_record_value(report, "completed_lessons", 0) or 0)
    completed_word_tests = int(_record_value(report, "completed_word_tests", 0) or 0)
    completed_games = int(_record_value(report, "completed_games", 0) or 0)
    current_streak = int((streak or {}).get("current_streak") or 0)
    longest_streak = int((streak or {}).get("longest_streak") or 0)
    completed_days = int((streak or {}).get("completed_days") or 0)
    today_completed = bool((streak or {}).get("today_completed"))

    badges = [
        _motivation_badge("first_lesson", "Первый урок", "Завершить один ежедневный урок.", completed_lessons, 1, "daily"),
        _motivation_badge("three_day_streak", "Три дня подряд", "Учиться три дня без перерыва.", current_streak, 3, "daily"),
        _motivation_badge("seven_day_streak", "Неделя английского", "Собрать серию из семи дней.", current_streak, 7, "daily"),
        _motivation_badge("word_collector", "10 слов", "Добавить первые десять слов в обучение.", words_learned, 10, "vocab"),
        _motivation_badge("word_builder", "50 слов", "Уверенно расширять словарь.", words_learned, 50, "vocab"),
        _motivation_badge("test_starter", "Первый тест", "Пройти тест по новым словам.", completed_word_tests, 1, "vocab"),
        _motivation_badge("game_player", "Игровая практика", "Закрепить слова в игровой практике.", completed_games, 3, "learn"),
        _motivation_badge("careful_answer", "30 верных ответов", "Набрать 30 правильных ответов.", total_correct, 30, "training"),
    ]
    unlocked_count = sum(1 for badge in badges if badge["unlocked"])

    if not today_completed:
        next_action = "daily"
        next_title = "Сделать урок дня"
        next_text = "Короткий урок сохранит серию и даст новые слова без перегруза."
    elif review_words > 0:
        next_action = "review"
        next_title = f"Повторить {review_words} слов"
        next_text = "Подошёл интервал повторения — повтори эти слова, чтобы они закрепились надолго."
    elif words_learned < 10:
        next_action = "vocab"
        next_title = "Собрать первые 10 слов"
        next_text = "Небольшой словарь даст материал для игр и устной практики."
    elif current_streak < 3:
        next_action = "learn"
        next_title = "Дополнительная тренировка"
        next_text = "Сегодняшний урок уже зачтен. Можно потренироваться еще, а серия продолжится завтра."
    elif completed_games < 3:
        next_action = "learn"
        next_title = "Закрепить слова"
        next_text = "Открой учебный раздел и выбери подходящую тренировку."
    elif completed_word_tests < 3:
        next_action = "vocab"
        next_title = "Пройти еще один тест"
        next_text = "Мини-тест покажет, какие слова уже стали уверенными."
    else:
        next_action = "learn"
        next_title = "Выбрать учебную тренировку"
        next_text = "Можно взять новые слова или повторить сложные."

    accuracy_total = total_correct + total_wrong
    accuracy = round(total_correct / accuracy_total * 100) if accuracy_total else 0
    coach_message = (
        "Сегодня урок уже засчитан. Можно сделать легкое повторение или короткую тренировку."
        if today_completed else
        "Лучший темп для ребенка: 5 минут сегодня, без длинной теории."
    )

    return {
        "title": "Достижения",
        "coach_message": coach_message,
        "next_action": next_action,
        "next_title": next_title,
        "next_text": next_text,
        "streak": {
            "current": current_streak,
            "longest": longest_streak,
            "completed_days": completed_days,
            "today_completed": today_completed,
        },
        "summary": {
            "unlocked_badges": unlocked_count,
            "total_badges": len(badges),
            "words_learned": words_learned,
            "completed_lessons": completed_lessons,
            "completed_word_tests": completed_word_tests,
            "completed_games": completed_games,
            "accuracy": accuracy,
        },
        "badges": badges,
    }


# ---------- API: профиль и регистрация ----------

async def api_me(request: web.Request):
    tg_user = request["tg_user"]
    user_id = tg_user["id"]
    is_admin = _is_admin_user_id(user_id)

    user = await database.get_user(user_id)
    if not user:
        return web.json_response({
            "registered": False,
            "is_admin": is_admin,
            "tg_user": {
                "id": tg_user["id"],
                "first_name": tg_user.get("first_name", ""),
            },
            "age_groups": [{"value": v, "label": l} for l, v in AGE_GROUPS],
            "goals": [{"value": v, "label": l} for l, v in LEARNING_GOALS],
            "levels": [{"value": v, "label": l} for l, v in ENGLISH_LEVELS],
        })

    stats = await database.get_user_stats(user_id)
    level = _level_for_user(user)
    age_group = _normalized_age_group_for_user(user)
    return web.json_response({
        "registered": True,
        "is_admin": is_admin,
        "user": {
            "id":         user["user_id"],
            "child_name": user["name"],
            "parent_name": user["parent_name"] or "",
            "child_age": user["child_age"],
            "age_group":  age_group,
            "age_label":  _age_label(age_group),
            "goal": user["goal"] or "",
            "goal_label": _goal_label(user["goal"]),
            "level": level,
            "level_label": _level_label(level),
            "level_test_score": _record_value(user, "level_test_score"),
            "level_test_completed": bool(_record_value(user, "level_test_completed_at")),
            "points":     user["points"],
        },
        "stats": {
            "words_learned": stats["words_learned"],
            "total_correct": stats["total_correct"],
            "total_wrong":   stats["total_wrong"],
        },
    })


async def api_admin_user_detail(request: web.Request):
    if not _is_admin_request(request):
        return _admin_forbidden_response()
    try:
        target_user_id = int(request.query.get("user_id") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "Некорректный user_id"}, status=400)
    user = await database.get_user(target_user_id)
    if not user:
        return web.json_response({"error": "Пользователь не найден"}, status=404)
    stats = await database.get_user_stats(target_user_id)
    report = await database.get_parent_report(target_user_id)
    dictionary_summary = await database.get_dictionary_summary(target_user_id)
    problem_words = await database.get_problem_words(target_user_id, limit=8)
    history = await database.get_activity_history(target_user_id, limit=12)
    ai_today = await database.get_ai_usage_today(target_user_id)
    streak = await database.get_learning_streak(target_user_id)
    return web.json_response(_admin_user_detail_payload(
        user,
        stats,
        report,
        dictionary_summary,
        problem_words,
        history,
        ai_today,
        streak,
    ))


async def api_leaderboard(request: web.Request):
    user_id = request["tg_user"]["id"]
    rows = await database.get_leaderboard(limit=10)

    leaders = []
    for index, row in enumerate(rows, start=1):
        age_label = next((l for l, v in AGE_GROUPS if v == row["age_group"]), row["age_group"])
        leaders.append({
            "rank": index,
            "name": row["name"],
            "age_label": age_label,
            "points": row["points"],
            "is_me": row["user_id"] == user_id,
        })

    return web.json_response({"leaders": leaders})


async def api_learning_path(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    daily_status = await database.get_daily_lesson_status(user_id)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    report = await database.get_parent_report(user_id)
    return web.json_response(
        _learning_path_payload(user, daily_status, stats, dictionary_summary, report)
    )


async def api_motivation_status(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    report = await database.get_parent_report(user_id)
    streak = await database.get_learning_streak(user_id)
    return web.json_response(
        _motivation_payload(user, stats, dictionary_summary, report, streak)
    )


async def api_register(request: web.Request):
    tg_user = request["tg_user"]
    body = await _safe_json(request)
    name = (body.get("child_name") or body.get("name") or "").strip()
    parent_name = (body.get("parent_name") or "").strip()
    goal = body.get("goal", "")
    try:
        child_age = int(body.get("child_age") or 0)
    except (TypeError, ValueError):
        child_age = 0

    if len(name) < 2 or len(name) > 30:
        return web.json_response({"error": "Имя ребенка должно быть от 2 до 30 символов"}, status=400)
    if parent_name and (len(parent_name) < 2 or len(parent_name) > 30):
        return web.json_response({"error": "Имя родителя должно быть от 2 до 30 символов"}, status=400)
    if child_age < 5 or child_age > 18:
        return web.json_response({"error": "Возраст ребенка должен быть от 5 до 18 лет"}, status=400)
    if goal and goal not in {v for _, v in LEARNING_GOALS}:
        return web.json_response({"error": "Некорректная цель обучения"}, status=400)

    # Возрастную группу больше не выбирают вручную — выводим из точного возраста.
    age_group = _age_group_from_age(child_age)

    await database.add_user(
        tg_user["id"],
        name,
        age_group,
        parent_name=parent_name or tg_user.get("first_name", ""),
        child_age=child_age,
        goal=goal or None,
        english_level=_level_from_score(age_group, 0, 0),
    )
    return web.json_response({"ok": True})


async def api_level_test(request: web.Request):
    user = await _current_user_or_404(request)
    age_group = _normalized_age_group_for_user(user)
    level = _level_for_user(user)
    questions = _level_questions_for_age(age_group)
    return web.json_response({
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "level": level,
        "level_label": _level_label(level),
        "questions": [_public_level_question(question) for question in questions],
    })


async def api_level_submit(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    answers = body.get("answers") or []
    if not isinstance(answers, list):
        return web.json_response({"error": "bad payload"}, status=400)

    age_group = _normalized_age_group_for_user(user)
    questions = _level_questions_for_age(age_group)
    by_id = {question["id"]: question for question in questions}
    selected_by_question = {}
    for raw in answers:
        if not isinstance(raw, dict):
            continue
        question_id = str(raw.get("question_id") or "")
        selected_id = str(raw.get("selected_id") or "")
        if question_id in by_id and selected_id:
            selected_by_question[question_id] = selected_id

    results = []
    correct_count = 0
    for question in questions:
        selected_id = selected_by_question.get(question["id"])
        correct = selected_id == question["correct_id"]
        if correct:
            correct_count += 1
        results.append({
            "question_id": question["id"],
            "correct": correct,
            "selected_id": selected_id,
            "correct_id": question["correct_id"],
        })

    total = len(questions)
    score = round(correct_count / total * 100) if total else 0
    level = _level_from_score(age_group, correct_count, total)
    await database.update_user_level(user_id, level, score)
    return web.json_response({
        "correct_count": correct_count,
        "total": total,
        "score": score,
        "level": level,
        "level_label": _level_label(level),
        "message": _level_result_message(level),
        "results": results,
    })


async def api_parent_report(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    report = await database.get_parent_report(user_id)
    stats = await database.get_user_stats(user_id)
    dictionary_summary = await database.get_dictionary_summary(user_id)
    problem_word_rows = await database.get_problem_words(user_id, limit=6)
    problem_words = [_problem_word_dict(row) for row in problem_word_rows]
    level = _level_for_user(user)
    report_payload = {
        "words_learned": int((report or stats)["words_learned"] or 0),
        "total_correct": int((report or stats)["total_correct"] or 0),
        "total_wrong": int((report or stats)["total_wrong"] or 0),
        "completed_lessons": int(report["completed_lessons"] if report else 0),
        "completed_word_tests": int(report["completed_word_tests"] if report else 0),
        "avg_word_test_score": int(report["avg_word_test_score"] if report else 0),
        "completed_games": int(report["completed_games"] if report else 0),
        "avg_game_score": int(report["avg_game_score"] if report else 0),
    }
    return web.json_response({
        "child": {
            "name": user["name"],
            "age_group": user["age_group"],
            "age_label": _age_label(user["age_group"]),
            "child_age": _record_value(user, "child_age"),
            "goal_label": _goal_label(user["goal"]),
            "level_label": _level_label(level),
            "points": user["points"],
        },
        "report": report_payload,
        "dictionary": {
            "total_words": int(dictionary_summary["total_words"] if dictionary_summary else 0),
            "mastered_words": int(dictionary_summary["mastered_words"] if dictionary_summary else 0),
            "review_words": int(dictionary_summary["review_words"] if dictionary_summary else 0),
        },
        "problem_words": problem_words,
        "recommendations": _parent_recommendations(report_payload, dictionary_summary, problem_words),
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


async def api_account_delete(request: web.Request):
    """Полное удаление профиля и всех данных ребёнка (QA H6)."""
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    if body.get("confirm") != "delete_account":
        return web.json_response({"error": "Нужно подтвердить удаление аккаунта"}, status=400)

    await database.delete_user_account(user_id)
    return web.json_response({"ok": True, "deleted": True})


async def api_activity_history(request: web.Request):
    user_id = request["tg_user"]["id"]
    try:
        limit = int(request.query.get("limit") or 30)
    except (TypeError, ValueError):
        limit = 30
    limit = max(5, min(limit, 80))
    rows = await database.get_activity_history(user_id, limit=limit)
    events = [_activity_event_dict(row) for row in rows]
    return web.json_response({
        "events": events,
        "summary": {
            "total_events": len(events),
            "active_days": len({event["date"] for event in events if event["date"]}),
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
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    exclude_id = body.get("current_id")
    age_group = _normalized_age_group_for_user(user)
    word = await database.get_practice_word(user_id, exclude_id=exclude_id, age_group=age_group)
    return web.json_response(_word_dict(word, _level_for_user(user)))


async def api_vocab_image_generate(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    try:
        word_id = int(body.get("word_id"))
    except (TypeError, ValueError):
        return web.json_response({"error": "bad payload"}, status=400)

    force = bool(body.get("force"))
    word = await database.get_word_by_id(word_id)
    if not word:
        return web.json_response({"error": "word not found"}, status=404)

    word_payload = _word_dict(word, _level_for_user(user))
    fallback_image_url = word_payload["fallback_image_url"]
    prompt_hash = word_payload["image_prompt_hash"]
    stored_url = word_payload.get("generated_image_url", "")
    stored_status = word_payload.get("image_generation_status", "missing")
    if not force and stored_url and _generated_vocab_url_exists(stored_url):
        return web.json_response({
            "image_url": stored_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": stored_status,
            "image_review": {},
            "cached": True,
        })

    if not force and GENERATED_VOCAB_DIR is not None and GENERATED_VOCAB_DIR.exists():
        for cached_path in GENERATED_VOCAB_DIR.glob(f"{prompt_hash}.*"):
            if not cached_path.is_file():
                continue
            cached_url = _generated_vocab_static_url(cached_path.name)
            await database.update_word_generated_image(
                word_id,
                image_url=cached_url,
                prompt_hash=prompt_hash,
                review_json="{}",
                status="generated",
                model="local-cache",
            )
            return web.json_response({
                "image_url": cached_url,
                "fallback_image_url": fallback_image_url,
                "generation_status": "generated",
                "image_review": {},
                "cached": True,
            })

    try:
        result = await asyncio.wait_for(generate_vocabulary_image(word_payload, user_id), timeout=75)
    except Exception as exc:
        log.exception("Vocabulary image generation failed for word_id=%s", word_id)
        await _record_ai_cost(user_id, OPENAI_IMAGE_MODEL, OPENAI_IMAGE_COST_PER_CALL)
        public_error = public_openai_error(exc)
        review_json = json.dumps({"reason": public_error}, ensure_ascii=False)
        try:
            await database.update_word_generated_image(
                word_id,
                image_url="",
                prompt_hash=prompt_hash,
                review_json=review_json,
                status="failed",
                model=OPENAI_IMAGE_MODEL,
            )
        except Exception:
            log.exception("Failed to persist vocabulary image failure for word_id=%s", word_id)
        return web.json_response({
            "error": public_error,
            "image_url": fallback_image_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": "failed",
            "image_review": {"reason": public_error},
        }, status=502)

    # result получен (успех или fail-после-генерации) — обе ветки потратили попытки.
    await _record_ai_cost(
        user_id,
        OPENAI_IMAGE_MODEL,
        max(1, int(getattr(result, "attempts", 1) or 1)) * OPENAI_IMAGE_COST_PER_CALL,
    )
    review_json = json.dumps(result.review, ensure_ascii=False)
    if result.generation_status == "failed" or not result.image_bytes:
        await database.update_word_generated_image(
            word_id,
            image_url="",
            prompt_hash=prompt_hash,
            review_json=review_json,
            status="failed",
            model=result.model,
        )
        return web.json_response({
            "image_url": fallback_image_url,
            "fallback_image_url": fallback_image_url,
            "generation_status": "failed",
            "image_review": result.review,
            "attempts": result.attempts,
        })

    extension = _generated_vocab_extension(result.content_type)
    filename = f"{prompt_hash}.{extension}"
    await storage.vocab_image_storage.write(filename, result.image_bytes)
    if GENERATED_VOCAB_DIR is not None:  # eviction только для локального диска (S3 — lifecycle)
        _evict_cache_dir(GENERATED_VOCAB_DIR, VOCAB_IMAGE_CACHE_MAX_FILES)
    image_url = _generated_vocab_static_url(filename)
    await database.update_word_generated_image(
        word_id,
        image_url=image_url,
        prompt_hash=prompt_hash,
        review_json=review_json,
        status=result.generation_status,
        model=result.model,
    )
    return web.json_response({
        "image_url": image_url,
        "fallback_image_url": fallback_image_url,
        "generation_status": result.generation_status,
        "image_review": result.review,
        "attempts": result.attempts,
        "cached": False,
    })


async def api_dictionary(request: web.Request):
    user_id = request["tg_user"]["id"]
    filter_mode = (request.query.get("filter") or "all").strip()
    if filter_mode not in {"all", "review", "mastered"}:
        filter_mode = "all"
    try:
        limit = int(request.query.get("limit") or 5000)
    except (TypeError, ValueError):
        limit = 5000
    limit = max(10, min(limit, 5000))

    rows = await database.get_user_dictionary(user_id, filter_mode=filter_mode, limit=limit)
    summary = await database.get_dictionary_summary(user_id)
    total_words = await database.get_words_count()
    return web.json_response({
        "filter": filter_mode,
        "summary": {
            "total_words": int(total_words or 0),
            "mastered_words": int(summary["mastered_words"] if summary else 0),
            "review_words": int(summary["review_words"] if summary else 0),
        },
        "words": [_dictionary_word_dict(row) for row in rows],
    })


async def api_vocab_start(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    topic = (body.get("topic") or "").strip() or None
    age_group = _normalized_age_group_for_user(user)
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
        "words": [_word_dict(w, _level_for_user(user)) for w in words],
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
    # Анти-N+1: пул дистракторов загружаем ОДНИМ запросом на весь квиз,
    # дальше варианты для каждого вопроса набираем в памяти.
    pool = await database.get_random_words(
        max(12, len(words) + 9), age_group=session["age_group"]
    )
    questions = [
        await _build_vocab_question(word, session["age_group"], idx, pool)
        for idx, word in enumerate(words)
    ]
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
    latest_result_by_word_id: dict[int, dict] = {}
    progress_updates: list[tuple[int, bool]] = []
    correct_count = 0
    wrong_count = 0
    total_delta = 0

    # Защита от накрутки очков: не больше одного ответа на слово, и только слова
    # этой сессии. Иначе клиент мог слать дубли и фармить очки без ограничений.
    answers_by_word: dict[int, dict] = {}
    for raw in (answers if isinstance(answers, list) else []):
        try:
            wid = int(raw.get("word_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if wid in words_by_id:
            answers_by_word[wid] = raw
    answers = list(answers_by_word.values())

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
        progress_updates.append((word_id, correct))
        result_item = {
            "word_id": word_id,
            "word": word["word"],
            "translation": word["translation"],
            "transcription": word["transcription"] or "",
            "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
            "correct": correct,
        }
        results.append(result_item)
        latest_result_by_word_id[word_id] = result_item

    await database.update_progress_bulk(user_id, progress_updates)
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
        "results": [
            latest_result_by_word_id[word["id"]]
            for word in words
            if word["id"] in latest_result_by_word_id
        ],
        "attempts": results,
    })


async def api_word_hunt_start(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    age_group = _normalized_age_group_for_user(user)
    count = min(6, max(4, WORDS_PER_AGE_GROUP.get(age_group, 6)))
    words = await database.get_words_for_age(age_group, count=count)
    if not words:
        return web.json_response({"error": "Пока не удалось загрузить слова для игры"}, status=500)

    session = await database.create_game_session(
        user_id=user_id,
        game_type="word_hunt",
        age_group=age_group,
        word_ids=[word["id"] for word in words],
    )
    # Анти-N+1: один запрос на пул дистракторов для всех раундов.
    pool = await database.get_random_words(max(12, len(words) + 9), age_group=age_group)
    rounds = [await _build_word_hunt_round(word, age_group, pool) for word in words]
    return web.json_response({
        "session_id": session["id"],
        "game_type": "word_hunt",
        "title": _game_title("word_hunt"),
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "rounds": rounds,
        "points_correct": GAME_POINTS_CORRECT,
        "perfect_bonus": GAME_PERFECT_BONUS_POINTS,
    })


async def api_word_hunt_finish(request: web.Request):
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    try:
        session_id = int(body["session_id"])
        answers = body["answers"]
    except (KeyError, ValueError, TypeError):
        return web.json_response({"error": "bad payload"}, status=400)

    session = await database.get_game_session(session_id, user_id)
    if not session:
        return web.json_response({"error": "game not found"}, status=404)
    if session["completed"]:
        return web.json_response({"error": "Эта игра уже завершена"}, status=400)

    words = await database.get_words_by_ids(list(session["word_ids"]))
    answer_by_word: dict[int, int] = {}
    for raw in answers:
        try:
            word_id = int(raw.get("word_id"))
            selected_id = int(raw.get("selected_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        answer_by_word[word_id] = selected_id

    results = []
    progress_updates: list[tuple[int, bool]] = []
    correct_count = 0
    wrong_count = 0

    for word in words:
        word_id = int(word["id"])
        selected_id = answer_by_word.get(word_id)
        correct = selected_id == word_id
        if correct:
            correct_count += 1
        else:
            wrong_count += 1
        progress_updates.append((word_id, correct))
        results.append({
            "word_id": word_id,
            "word": word["word"],
            "translation": word["translation"],
            "transcription": word["transcription"] or "",
            "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
            "selected_id": selected_id,
            "correct": correct,
        })

    total = correct_count + wrong_count
    perfect_bonus = GAME_PERFECT_BONUS_POINTS if total > 0 and correct_count == total else 0
    total_delta = correct_count * GAME_POINTS_CORRECT + perfect_bonus
    await database.update_progress_bulk(user_id, progress_updates)
    await database.finish_game_session(session_id, user_id, correct_count, wrong_count)
    await database.update_points(user_id, total_delta)
    user = await database.get_user(user_id)
    return web.json_response({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "total": total,
        "score": round(correct_count / total * 100) if total else 0,
        "delta": total_delta,
        "perfect_bonus": perfect_bonus,
        "points": user["points"] if user else 0,
        "results": results,
    })


# ---------- Static ----------

_INDEX_HTML_CACHE: str | None = None


def _render_index_html() -> str:
    text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return text.replace("__APP_VERSION__", APP_VERSION)


async def index_handler(request: web.Request):
    # index.html кэшируется в памяти (читать с диска на каждый запрос — это
    # блокирующий I/O в event loop). Для dev кэш можно отключить переменной
    # окружения INDEX_HTML_NO_CACHE=1, чтобы видеть правки без рестарта.
    global _INDEX_HTML_CACHE
    if _INDEX_HTML_CACHE is None or os.getenv("INDEX_HTML_NO_CACHE"):
        _INDEX_HTML_CACHE = _render_index_html()
    return web.Response(
        text=_INDEX_HTML_CACHE,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


async def word_image_handler(request: web.Request):
    word = " ".join((request.query.get("w") or "word").split())[:48]
    topic = " ".join((request.query.get("t") or "basic").split())[:32]
    return web.Response(
        text=_word_image_svg(word, topic),
        content_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=604800",
        },
    )


async def vocabulary_visual_handler(request: web.Request):
    word = " ".join((request.query.get("w") or "word").split())[:48]
    topic = " ".join((request.query.get("t") or "basic").split())[:32]
    visual_type = " ".join((request.query.get("v") or "object").split())[:32]
    return web.Response(
        text=_vocabulary_visual_svg(word, topic, visual_type),
        content_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=604800",
        },
    )


# ---------- App factory ----------

def _log_slow_or_failed_api(request: web.Request, status: int, started: float) -> None:
    """Логирует только медленные (>2с) или ошибочные (5xx) API-запросы — без спама."""
    if not request.path.startswith("/api/"):
        return
    latency_ms = int((time.monotonic() - started) * 1000)
    if status >= 500 or latency_ms > 2000:
        user_id = (request.get("tg_user") or {}).get("id", "")
        log.warning(
            "api %s %s -> %s %dms user=%s",
            request.method, request.path, status, latency_ms, user_id,
        )


@web.middleware
async def hardening_middleware(request: web.Request, handler):
    """Ловит необработанные исключения (без утечки трейсбека), ставит nosniff
    и логирует медленные/ошибочные API-запросы для отладки."""
    started = time.monotonic()
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        _log_slow_or_failed_api(request, exc.status, started)
        raise
    except Exception:
        log.exception("Необработанная ошибка на %s %s", request.method, request.path)
        response = web.json_response({"error": "Внутренняя ошибка сервера"}, status=500)
    # Заголовки безопасности на ВСЕ ответы (не только /api/). X-Frame-Options НЕ
    # ставим — Mini App должен грузиться внутри iframe Telegram. Уже отправленные
    # StreamResponse (стриминг аудио/фото) не трогаем.
    if not getattr(response, "prepared", False):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # CSP: мягкая, не ломающая Telegram WebView (инлайн-стили нужны фронту,
        # картинки/фото грузятся с https и data:, голос — по wss).
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self' https: wss:; "
            "media-src 'self' data: https: blob:; "
            "object-src 'none'; "
            "base-uri 'self'",
        )
        # Статика: долгий кэш (ассеты версионируются через ?v=APP_VERSION) и
        # gzip для текстовых файлов — ускоряет загрузку app.js/css на мобильном.
        if request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
            if request.path.endswith((".js", ".css", ".svg", ".json", ".map")):
                try:
                    response.enable_compression()
                except (AttributeError, RuntimeError):
                    pass
        # API-ответы JSON тоже сжимаем — особенно тяжёлый /api/dictionary (до 5000
        # слов). gzip включается только если клиент прислал Accept-Encoding: gzip.
        elif request.path.startswith("/api/") and \
                (response.content_type or "").startswith("application/json"):
            try:
                response.enable_compression()
            except (AttributeError, RuntimeError):
                pass
    _log_slow_or_failed_api(request, response.status, started)
    return response


async def healthz_handler(request: web.Request):
    """Liveness-проба для Render/Docker (без обращения к БД, всегда быстрая)."""
    return web.Response(text="ok")


def _generated_dir_under_static() -> bool:
    """True, если каталог сгенерированных картинок лежит внутри STATIC_DIR
    (тогда их раздаёт обычный add_static). Если CACHE_ROOT вынесен наружу —
    нужна отдельная раздача (см. generated_vocab_image_handler)."""
    if GENERATED_VOCAB_DIR is None:
        return False  # S3/R2 — раздаём своим маршрутом-прокси
    try:
        GENERATED_VOCAB_DIR.resolve().relative_to(STATIC_DIR.resolve())
        return True
    except (ValueError, OSError):
        return False


_GENERATED_IMAGE_CTYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}


async def generated_vocab_image_handler(request: web.Request):
    """Прокси-раздача сгенерированной картинки слова из хранилища (локальный диск
    вне static или S3/R2). URL-схема та же: /static/generated/vocabulary/<file>,
    поэтому ссылки в БД не меняются. Бакет может быть приватным."""
    name = request.match_info.get("name", "")
    if not name or "/" in name or "\\" in name or ".." in name:
        raise web.HTTPNotFound()
    try:
        data = await storage.vocab_image_storage.read(name)
    except Exception:  # noqa: BLE001 — нет объекта/файла
        raise web.HTTPNotFound()
    ctype = _GENERATED_IMAGE_CTYPES.get(name.rsplit(".", 1)[-1].lower(), "image/png")
    return web.Response(
        body=data, content_type=ctype,
        headers={"Cache-Control": "public, max-age=604800"},
    )


def create_app(
    bot=None,
    dispatcher=None,
    webhook_path: str | None = None,
    webhook_secret: str | None = None,
) -> web.Application:
    app = web.Application(
        middlewares=[hardening_middleware, auth_middleware],
        client_max_size=MAX_AUDIO_BYTES + 1024 * 1024,
    )

    app.router.add_get("/healthz", healthz_handler)
    app.router.add_get("/",        index_handler)
    app.router.add_get("/word-image.svg", word_image_handler)
    app.router.add_get("/vocabulary-visual.svg", vocabulary_visual_handler)
    app.router.add_get("/vocabulary-photo", vocabulary_photo_handler)
    app.router.add_get("/api/me",  api_me)
    app.router.add_get("/api/admin/overview",           api_admin_overview)
    app.router.add_get("/api/admin/users",              api_admin_users)
    app.router.add_get("/api/admin/users/detail",       api_admin_user_detail)
    app.router.add_post("/api/admin/users/reset-results", api_admin_reset_user_results)
    app.router.add_post("/api/admin/images/reset-failed", api_admin_reset_image_failures)
    app.router.add_get("/api/leaderboard",              api_leaderboard)
    app.router.add_get("/api/learning/path",            api_learning_path)
    app.router.add_get("/api/motivation/status",        api_motivation_status)
    app.router.add_get("/api/parent/report",            api_parent_report)
    app.router.add_post("/api/results/reset",           api_results_reset)
    app.router.add_post("/api/account/delete",          api_account_delete)
    app.router.add_get("/api/activity/history",         api_activity_history)
    app.router.add_get("/api/level/test",               api_level_test)
    app.router.add_post("/api/level/submit",            api_level_submit)
    app.router.add_get("/api/daily/status",             api_daily_status)
    app.router.add_post("/api/daily/progress",          api_daily_progress)
    app.router.add_post("/api/register",               api_register)
    app.router.add_get("/api/dictionary",              api_dictionary)
    app.router.add_post("/api/learn/next",             api_learn_next)
    app.router.add_post("/api/vocab/image/generate",   api_vocab_image_generate)
    app.router.add_post("/api/vocab/start",            api_vocab_start)
    app.router.add_post("/api/vocab/quiz",             api_vocab_quiz)
    app.router.add_post("/api/vocab/finish",           api_vocab_finish)
    app.router.add_post("/api/game/word-hunt/start",   api_word_hunt_start)
    app.router.add_post("/api/game/word-hunt/finish",  api_word_hunt_finish)
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

    # Если кэш вынесен за static (CACHE_ROOT на persistent disk) — раздаём
    # сгенерированные картинки своим маршрутом ДО add_static (та же URL-схема).
    if not _generated_dir_under_static():
        app.router.add_get(
            "/static/generated/vocabulary/{name}", generated_vocab_image_handler
        )
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
