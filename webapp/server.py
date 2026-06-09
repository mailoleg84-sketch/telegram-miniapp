"""aiohttp-сервер: статика Mini App + JSON API."""
import asyncio
import base64
from collections import defaultdict, deque
import hashlib
import json
import logging
import os
import random
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database
from config import (
    ADMIN_USER_IDS,
    AGE_GROUPS,
    age_group_from_age,
    AI_DAILY_MESSAGE_LIMIT,
    AI_RATE_LIMIT_PER_MINUTE,
    REALTIME_DAILY_SESSION_LIMIT,
    REALTIME_TOKEN_TIMEOUT_SEC,
    API_RATE_LIMIT_PER_MINUTE,
    APP_VERSION,
    BOT_RUN_MODE,
    CHAT_HISTORY_LIMIT,
    DAILY_LESSON_REWARD_POINTS,
    DAILY_LESSON_STEPS,
    ENGLISH_LEVELS,
    GAME_PERFECT_BONUS_POINTS,
    GAME_POINTS_CORRECT,
    LEARNING_GOALS,
    POINTS_CORRECT,
    POINTS_WRONG,
    TUTOR_DEFAULT_LEVEL,
    WORDS_PER_AGE_GROUP,
    WEBAPP_HOST,
    WEBAPP_PORT,
    WEBAPP_URL,
    OPENAI_IMAGE_MODEL,
    VOCAB_AI_IMAGES,
    VOCAB_FREE_PHOTOS,
    PIXABAY_API_KEY,
    OPENAI_TTS_MODEL,
    OPENAI_REALTIME_MODEL,
    OPENAI_TTS_COST_PER_1K_CHARS,
    OPENAI_IMAGE_COST_PER_CALL,
    OPENAI_REALTIME_SESSION_COST,
)
from webapp.auth import verify_fallback_auth, verify_init_data
from webapp.lesson_engine import (
    advance_lesson_state,
    create_lesson_state,
    lesson_prompt_context,
    public_lesson_state,
)
from webapp.openai_service import (
    chat_reply,
    create_realtime_call,
    create_realtime_client_secret,
    generate_vocabulary_image,
    openai_config_status,
    public_openai_error,
    redact_personal_data,
    synthesize_speech,
    synthesize_speech_stream,
    transcribe_audio,
)
from webapp.vocabulary_visualizer import (
    build_vocabulary_visual,
    vocabulary_image_url,
    emoji_for,
    is_sensitive_word,
)
from webapp.free_images import fetch_word_illustration
from webapp import storage
from webapp import redis_store

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
# Каталоги кэшей берём из слоя хранилища (webapp/storage.py). По умолчанию это
# <static>/generated (как раньше); через переменную окружения CACHE_ROOT можно
# вынести их на постоянный диск Render, чтобы кэши переживали деплой.
# Для локального backend — каталог (Path); для S3/R2 — None (нет локального пути).
GENERATED_VOCAB_DIR = getattr(storage.vocab_image_storage, "base_dir", None)
AUDIO_CACHE_DIR = getattr(storage.word_audio_storage, "base_dir", None)
VOCAB_PHOTO_CACHE_DIR = getattr(storage.vocab_photo_storage, "base_dir", None)
VOCAB_PHOTO_CACHE_MAX_FILES = int(os.getenv("VOCAB_PHOTO_CACHE_MAX_FILES", "800"))
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SDP_BYTES = 16 * 1024  # реальный WebRTC SDP < 4 КБ; жёсткий предел тела
# Кэши на эфемерном диске Render не должны расти бесконечно (QA-аудит).
AUDIO_CACHE_MAX_FILES = int(os.getenv("AUDIO_CACHE_MAX_FILES", "4000"))
VOCAB_IMAGE_CACHE_MAX_FILES = int(os.getenv("VOCAB_IMAGE_CACHE_MAX_FILES", "4000"))
PUBLIC_API_PATHS = {"/api/me", "/api/register"}
# Лимитирование вынесено в webapp/rate_limiter.py.
from webapp.rate_limiter import (
    _photo_rate_limit_ok,
    _rate_buckets,
    _rate_limit_key,
    _rate_limit_ok,
    photo_rate_limit_ok,
    rate_limit_ok,
)


def _evict_cache_dir(directory: Path, max_files: int) -> None:
    """Удаляет самые старые файлы кэша, если их больше лимита (эфемерный диск).

    Логика вынесена в webapp/storage.evict_dir; .none-маркеры (слово без картинки)
    не выселяем — они крошечные и экономят квоту Pixabay.
    """
    try:
        storage.evict_dir(directory, max_files)
    except OSError:
        log.exception("Не удалось почистить кэш %s", directory)


# SVG-рендер вынесен в webapp/svg_renderer.py (чистые функции построения SVG).
from webapp.svg_renderer import (
    _word_image_icon,
    _word_image_svg,
    _vocabulary_visual_svg,
)
# Чистые форматтеры/метки/логика уровня вынесены в webapp/formatters.py
# (шаг рефакторинга 3a). Реэкспорт — чтобы существующие импорты и вызовы внутри
# server.py продолжали работать без изменений.
from webapp.formatters import (
    _record_value,
    _safe_int,
    _safe_float,
    _date_text,
    _age_label,
    _goal_label,
    _level_label,
    _estimated_level_for_user,
    _level_for_user,
    _level_from_score,
    _level_result_message,
    _level_questions_for_age,
    _public_level_question,
    _path_step,
    _game_title,
)

def _word_image_url(word: str, topic: str = "") -> str:
    clean_word = " ".join(str(word or "").split())[:48]
    clean_topic = " ".join(str(topic or "basic").split())[:32]
    if _word_image_icon(clean_word):
        query = urlencode({
            "w": clean_word,
            "t": clean_topic,
        })
        return f"/word-image.svg?{query}"
    visual = build_vocabulary_visual(
        word=clean_word,
        translation="",
        example_sentence="",
        topic=clean_topic,
    )
    svg_url = visual.get("image_url") or vocabulary_image_url(clean_word, visual.get("visual_type", "no_good_visual"), clean_topic)
    return _vocab_card_image_url(
        clean_word, svg_url, visual.get("emoji", ""),
        visual.get("visual_type", ""), clean_topic,
    )


# Бесплатное фото Pixabay уместно только для КОНКРЕТНЫХ, фотографируемых слов
# (предмет/действие). Для абстрактных/грамматических типов остаётся осмысленная
# SVG-сцена — это логичнее, чем случайное стоковое фото по голому слову.
PHOTO_VISUAL_TYPES = {"object", "action"}


def _vocab_card_image_url(
    word: str,
    fallback_url: str,
    emoji: str = "",
    visual_type: str = "",
    topic: str = "",
) -> str:
    """Free Pixabay photo for concrete words (object/action) without an emoji;
    otherwise the contextual SVG scene. Emoji words render a glyph client-side, so
    image_url just keeps the SVG fallback. Topic narrows the photo search."""
    w = " ".join(str(word or "").split()).lower()
    if (
        VOCAB_FREE_PHOTOS
        and w
        and not emoji
        and not is_sensitive_word(w)
        and visual_type in PHOTO_VISUAL_TYPES
    ):
        params = {"w": w[:40]}
        t = " ".join(str(topic or "").split()).lower()[:32]
        if t:
            params["t"] = t
        return "/vocabulary-photo?" + urlencode(params)
    return fallback_url


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

def _vocabulary_image_prompt_hash(visual: dict) -> str:
    payload = {
        key: str(visual.get(key) or "")
        for key in (
            "word",
            "translation",
            "visual_type",
            "image_prompt",
            "example_sentence",
            "simple_meaning",
            "russian_hint",
        )
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _generated_vocab_url_exists(url: str) -> bool:
    if not url or not url.startswith("/static/generated/vocabulary/"):
        return False
    filename = url.rsplit("/", 1)[-1]
    if not filename or "/" in filename or "\\" in filename:
        return False
    if GENERATED_VOCAB_DIR is None:
        # S3/R2 — хранилище персистентно: раз URL в БД, объект существует. Доверяем
        # (в отличие от эфемерного диска, где файл мог стереться при деплое).
        return True
    return (GENERATED_VOCAB_DIR / filename).is_file()


def _generated_vocab_extension(content_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }.get((content_type or "").lower(), "png")


def _generated_vocab_static_url(filename: str) -> str:
    return f"/static/generated/vocabulary/{filename}"


def _cacheable_word_audio(text: str, mode: str) -> bool:
    clean_text = " ".join(str(text or "").split())
    return mode == "word" and 0 < len(clean_text) <= 120


def _word_audio_cache_name(text: str, mode: str, speed) -> str | None:
    """Имя файла кэша озвучки (``<sha1>.mp3``) или None, если текст не кэшируем.
    Каталог/префикс добавляет слой хранилища (storage.word_audio_storage), поэтому
    одинаково работает и для локального диска, и для S3/R2."""
    if not _cacheable_word_audio(text, mode):
        return None
    clean_text = " ".join(str(text or "").split()).lower()
    speed_key = "" if speed in (None, "") else str(speed)
    raw = json.dumps({
        "mode": mode,
        "text": clean_text,
        "speed": speed_key,
        "format": "mp3",
        "v": 1,
    }, ensure_ascii=False, sort_keys=True)
    return f"{hashlib.sha1(raw.encode('utf-8')).hexdigest()}.mp3"


def _word_dict(word, learner_level: str = "beginner") -> dict:
    if not word:
        return {}
    def value(key: str, default=""):
        try:
            item = word[key]
        except (KeyError, IndexError, TypeError):
            return default
        return default if item is None else item

    transcription = value("transcription", "")
    topic = word["topic"] or "basic"
    visual = build_vocabulary_visual(
        word=value("word", ""),
        translation=value("translation", ""),
        example_sentence=value("example", ""),
        topic=topic,
        age_group=value("age_group", ""),
        level=learner_level,
    )
    visual.update({
        "word": value("word", ""),
        "translation": value("translation", ""),
    })
    emoji = visual.get("emoji", "")
    fallback_image_url = visual["image_url"]
    image_prompt_hash = _vocabulary_image_prompt_hash(visual)
    generated_image_url = value("generated_image_url", "")
    generated_image_status = value("generated_image_status", "missing") or "missing"
    generated_prompt_hash = value("generated_image_prompt_hash", "")
    if (
        generated_image_url
        and generated_prompt_hash == image_prompt_hash
        and generated_image_status in {"generated", "needs_review"}
        and _generated_vocab_url_exists(generated_image_url)
    ):
        image_url = generated_image_url
    else:
        image_url = _vocab_card_image_url(
            value("word", ""), fallback_image_url, emoji,
            visual.get("visual_type", ""), value("topic", ""),
        )
        if generated_image_status in {"generated", "needs_review"}:
            generated_image_status = "missing"

    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": transcription,
        "example": word["example"] or "",
        "topic": topic,
        "age_group": word["age_group"] or "",
        "part_of_speech": visual["part_of_speech"],
        "visual_type": visual["visual_type"],
        "image_prompt": visual["image_prompt"],
        "emoji": visual.get("emoji", ""),
        "image_url": image_url,
        "fallback_image_url": fallback_image_url,
        "generated_image_url": generated_image_url if image_url == generated_image_url else "",
        "image_can_generate": VOCAB_AI_IMAGES,
        "image_generation_status": generated_image_status,
        "image_prompt_hash": image_prompt_hash,
        "image_alt": visual["image_alt"],
        "example_sentence": visual["example_sentence"],
        "simple_meaning": visual["simple_meaning"],
        "russian_hint": visual["russian_hint"],
        "image_confidence": visual["image_confidence"],
        "image_needs_review": visual["needs_review"],
        "needs_review": visual["needs_review"],
        "generation_status": visual["generation_status"],
        "show_russian_hint": visual["show_russian_hint"],
    }


def _dictionary_word_dict(word) -> dict:
    data = _word_dict(word)
    correct_count = int(word["correct_count"] or 0)
    wrong_count = int(word["wrong_count"] or 0)
    mastered = bool(word["mastered"])
    needs_review = bool(word["needs_review"])
    # SRS: «пора повторить» важнее «выучено». Освоенное слово, у которого подошёл
    # интервал (needs_review=due), показываем как «повторить» — иначе оно с ярлыком
    # «выучено» молча выпадало бы из визуального потока повторения (и из фильтра).
    if needs_review:
        status = "review"
        status_label = "повторить"
    elif mastered:
        status = "mastered"
        status_label = "выучено"
    else:
        status = "learning"
        status_label = "учим"
    data.update({
        "correct_count": correct_count,
        "wrong_count": wrong_count,
        "needs_review": needs_review,
        "mastered": mastered,
        "status": status,
        "status_label": status_label,
    })
    return data


def _problem_word_dict(word) -> dict:
    return {
        "id": word["id"],
        "word": word["word"],
        "translation": word["translation"],
        "transcription": _word_dict(word).get("transcription", ""),
        "example": word["example"] or "",
        "image_url": _word_image_url(word["word"], word["topic"] or "basic"),
        "correct_count": int(word["correct_count"] or 0),
        "wrong_count": int(word["wrong_count"] or 0),
    }


async def _safe_json(request: web.Request) -> dict:
    if request.body_exists:
        try:
            return await request.json()
        except Exception:
            log.warning("Не удалось разобрать JSON тела запроса на %s %s",
                        request.method, request.path)
            return {}
    return {}


def _looks_like_audio(buf: bytes) -> bool:
    """Проверка magic-bytes: отсекаем заведомо не-аудио до отправки в Whisper.

    Поддержанные контейнеры: WebM/Matroska, OGG/Opus, MP3 (ID3 или frame sync),
    WAV/RIFF, MP4/M4A (ftyp), AIFF, FLAC. Защищает от cost-amplification.
    """
    if len(buf) < 12:
        return False
    head = buf[:12]
    if head[:4] == b"\x1a\x45\xdf\xa3":          # WebM / Matroska (EBML)
        return True
    if head[:4] == b"OggS":                       # OGG (Opus/Vorbis)
        return True
    if head[:3] == b"ID3":                         # MP3 с ID3-тегом
        return True
    if head[0] == 0xFF and (head[1] & 0xE0) == 0xE0:  # MP3 frame sync
        return True
    if head[:4] == b"RIFF" and buf[8:12] == b"WAVE":  # WAV
        return True
    if head[4:8] == b"ftyp":                       # MP4 / M4A
        return True
    if head[:4] == b"FORM":                         # AIFF
        return True
    if head[:4] == b"fLaC":                         # FLAC
        return True
    return False


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
    if not _looks_like_audio(audio):
        raise web.HTTPBadRequest(text="Неподдерживаемый формат аудио")

    return (
        audio,
        field.filename or "voice.webm",
        field.headers.get("Content-Type", "audio/webm"),
    )


async def _record_ai_cost(user_id: int, model: str, cost_usd: float, *, tokens: int = 0) -> None:
    """Учитывает расход OpenAI (TTS/картинки/Realtime) для видимости в админке.

    Никогда не ломает пользовательский поток: ошибки записи проглатываются.
    """
    try:
        await database.add_ai_usage(
            user_id=user_id,
            model=model,
            input_tokens=tokens,
            output_tokens=0,
            total_tokens=tokens,
            cost_usd=round(float(cost_usd), 6),
        )
    except Exception:
        log.exception("Не удалось записать расход AI (%s)", model)


def _chat_usage_payload(stats) -> dict:
    used = int(stats["requests"] if stats else 0)
    limit = AI_DAILY_MESSAGE_LIMIT
    unlimited = limit <= 0
    remaining = None if unlimited else max(0, limit - used)
    return {
        "used_today": used,
        "daily_limit": None if unlimited else limit,
        "remaining_today": remaining,
        "unlimited": unlimited,
        "limit_reached": (not unlimited) and used >= limit,
        "input_tokens_today": int(stats["input_tokens"] if stats else 0),
        "output_tokens_today": int(stats["output_tokens"] if stats else 0),
        "total_tokens_today": int(stats["total_tokens"] if stats else 0),
        "cost_usd_today": round(float(stats["cost_usd"] if stats else 0), 6),
    }


def _ai_daily_limit_reached(stats) -> bool:
    """True, если включён бесплатный лимит AI-уроков и он на сегодня исчерпан."""
    limit = AI_DAILY_MESSAGE_LIMIT
    if limit <= 0:
        return False
    return int(stats["requests"] if stats else 0) >= limit


def _ai_limit_message() -> str:
    return (
        "На сегодня бесплатные занятия с репетитором закончились. "
        "Возвращайся завтра! А пока можно учить слова, проходить тесты и "
        "играть — это без ограничений."
    )


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
        "cache": {
            "generated_images": _file_cache_summary(GENERATED_VOCAB_DIR) if GENERATED_VOCAB_DIR else {"backend": "r2"},
            "word_audio": _file_cache_summary(AUDIO_CACHE_DIR) if AUDIO_CACHE_DIR else {"backend": "r2"},
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


def _admin_user_dict(row) -> dict:
    total_answers = _safe_int(row, "total_correct") + _safe_int(row, "total_wrong")
    accuracy = round(_safe_int(row, "total_correct") / total_answers * 100) if total_answers else 0
    age_group = _record_value(row, "age_group", "")
    return {
        "id": _safe_int(row, "user_id"),
        "child_name": _record_value(row, "name", ""),
        "parent_name": _record_value(row, "parent_name", "") or "",
        "child_age": _record_value(row, "child_age", None),
        "age_group": age_group,
        "age_label": _age_label(age_group),
        "goal_label": _goal_label(_record_value(row, "goal", "")),
        "level_label": _level_label(_record_value(row, "english_level", "")),
        "level_test_score": _record_value(row, "level_test_score", None),
        "level_test_completed": bool(_record_value(row, "level_test_completed_at")),
        "points": _safe_int(row, "points"),
        "registered_at": _date_text(_record_value(row, "registered_at")),
        "words_learned": _safe_int(row, "words_learned"),
        "total_correct": _safe_int(row, "total_correct"),
        "total_wrong": _safe_int(row, "total_wrong"),
        "accuracy": accuracy,
        "completed_lessons": _safe_int(row, "completed_lessons"),
        "completed_word_tests": _safe_int(row, "completed_word_tests"),
        "completed_games": _safe_int(row, "completed_games"),
    }


def _admin_failed_image_dict(row) -> dict:
    raw_review = _record_value(row, "generated_image_review", "") or ""
    reason = ""
    try:
        parsed = json.loads(raw_review)
        reason = str(parsed.get("reason") or "")
    except Exception:
        reason = raw_review[:180]
    return {
        "id": _safe_int(row, "id"),
        "word": _record_value(row, "word", ""),
        "translation": _record_value(row, "translation", ""),
        "topic": _record_value(row, "topic", ""),
        "age_group": _record_value(row, "age_group", ""),
        "status": _record_value(row, "generated_image_status", "failed"),
        "reason": reason,
        "checked_at": _date_text(_record_value(row, "generated_image_checked_at")),
    }


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


def _activity_event_dict(row) -> dict:
    event_type = row["event_type"]
    if event_type == "daily_lesson":
        title = "Урок дня"
        description = "Урок завершён"
    elif event_type == "word_game":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Игровая практика"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type == "word_test":
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Учим слова"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    elif event_type in {"review_training", "word_training"}:
        correct_count = int(row["correct_count"] or 0)
        wrong_count = int(row["wrong_count"] or 0)
        title = "Работа над ошибками" if event_type == "review_training" else "Тренировка слов"
        description = f"{correct_count} из {correct_count + wrong_count} правильных · {int(row['score'] or 0)}%"
    else:
        title = "Тест уровня"
        description = f"Результат: {int(row['score'] or 0)}%"

    return {
        "type": event_type,
        "date": row["event_date"] or "",
        "event_at": _date_text(row["event_at"]),
        "title": title,
        "description": description,
        "score": row["score"],
    }


def _parent_recommendations(report: dict, dictionary_summary: dict, problem_words: list[dict]) -> list[dict]:
    words_learned = int(report.get("words_learned") or 0)
    completed_lessons = int(report.get("completed_lessons") or 0)
    completed_word_tests = int(report.get("completed_word_tests") or 0)
    avg_score = int(report.get("avg_word_test_score") or 0)
    total_wrong = int(report.get("total_wrong") or 0)
    review_words = int((dictionary_summary or {}).get("review_words") or 0)
    recommendations = []

    if completed_lessons == 0:
        recommendations.append({
            "title": "Начать с короткого урока",
            "text": "Пусть ребенок пройдет ежедневный урок на 5 минут: слова, мини-тест и простая фраза.",
            "action": "daily",
        })
    if words_learned == 0:
        recommendations.append({
            "title": "Добавить первые слова",
            "text": "Запустите набор новых слов с тестом, чтобы появился базовый словарь и первые результаты.",
            "action": "vocab",
        })
    if review_words > 0:
        recommendations.append({
            "title": "Повторить слова по расписанию",
            "text": f"{review_words} слов сегодня готовы к повторению — у них подошёл интервал. Короткая тренировка освежит их в памяти.",
            "action": "review",
        })
    if completed_word_tests > 0 and avg_score < 70:
        recommendations.append({
            "title": "Снизить сложность на один шаг",
            "text": "Средний результат тестов ниже 70%. Дайте больше повторения и короткие задания без спешки.",
            "action": "review",
        })
    if problem_words and total_wrong > 0:
        sample = ", ".join(word["word"] for word in problem_words[:3])
        recommendations.append({
            "title": "Фокус на конкретных словах",
            "text": f"Чаще всего ошибается в словах: {sample}. Их стоит повторить в короткой тренировке.",
            "action": "dictionary",
        })
    if not recommendations:
        recommendations.append({
            "title": "Продолжать текущий темп",
            "text": "Прогресс выглядит ровно. Достаточно 5-10 минут в день: урок, повторение и короткая устная практика.",
            "action": "daily",
        })
    return recommendations[:4]


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


def _age_group_from_age(age: int) -> str:
    """Возрастная группа из точного возраста (делегирует в config — единый
    источник «лестницы» возраст→группа). "" если вне 5-18."""
    return age_group_from_age(age)


def _normalized_age_group_for_user(user) -> str:
    age_group = user["age_group"] if user else ""
    if age_group in {"5_7", "8_10", "11_13", "14_18"}:
        return age_group
    try:
        child_age = int(user["child_age"] or 0) if user else 0
    except (TypeError, ValueError):
        child_age = 0
    derived = _age_group_from_age(child_age)
    if derived:
        return derived
    if age_group in {"under_12", "under12", "under_10"}:
        return "8_10"
    return "8_10"


def _prompt_context_for_user(user) -> dict:
    return {
        "age": str(user["child_age"] or _age_label(user["age_group"])) if user else "не указан",
        "age_group": _normalized_age_group_for_user(user),
        "level": _level_for_user(user),
        "goal": _goal_label(user["goal"]) if user else "устная практика",
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


def _voice_prompt_context(user, messages: list[dict], lesson_state: dict | None = None) -> dict:
    topics = _choose_voice_topics(user, messages)
    lesson_focus = _voice_lesson_focus(messages)
    has_history = any(str(message.get("content") or "").strip() for message in messages)
    recent_user_messages = [m["content"] for m in messages if m["role"] == "user"][-3:]
    recent_assistant_messages = [m["content"] for m in messages if m["role"] == "assistant"][-3:]
    context = {
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
    if lesson_state:
        context.update(lesson_prompt_context(lesson_state))
    return context


async def _ensure_voice_lesson_state(user_id: int, user) -> dict:
    row = await database.get_voice_lesson_state(user_id)
    age_group = _normalized_age_group_for_user(user)
    if row and row["age_group"] == age_group:
        return dict(row)
    state = create_lesson_state(
        age_group=age_group,
        goal=user["goal"] if user else "",
        seed=str(user_id),
    )
    await database.save_voice_lesson_state(user_id, state)
    return state


async def _advance_voice_lesson_state(user_id: int, user, role: str, text: str) -> dict:
    state = await _ensure_voice_lesson_state(user_id, user)
    previous_phase = state.get("phase")
    state = advance_lesson_state(state, role, text)
    await database.save_voice_lesson_state(user_id, state)
    if previous_phase != "wrapup" and state.get("phase") == "wrapup":
        await database.save_completed_voice_lesson(user_id, state)
    return state


async def _current_user_or_404(request: web.Request):
    user = await database.get_user(request["tg_user"]["id"])
    if not user:
        raise web.HTTPBadRequest(text="user is not registered")
    return user


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
        next_title = f"Продолжить урок: шаг {min(daily_steps + 1, DAILY_LESSON_STEPS)} из {DAILY_LESSON_STEPS}"
        next_text = "Сегодняшний план: слова, мини-тест, фраза и награда."
    elif words_learned == 0:
        next_action = "vocab"
        next_title = "Добавить первые слова"
        next_text = "Небольшой набор слов даст основу для игр и устной практики."
    elif review_words > 0:
        next_action = "review"
        next_title = f"Повторить {review_words} слов"
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


def _motivation_badge(
    badge_id: str,
    title: str,
    text: str,
    value: int,
    target: int,
    action: str,
) -> dict:
    target = max(1, target)
    value = max(0, value)
    return {
        "id": badge_id,
        "title": title,
        "text": text,
        "value": value,
        "target": target,
        "progress_percent": min(100, round(value / target * 100)),
        "unlocked": value >= target,
        "action": action,
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
        next_title = f"Повторить {review_words} слов"
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


# ---------- API: ИИ-репетитор ----------

async def api_chat_history(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT * 2)
    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    stats = await database.get_ai_usage_today(user_id)
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    return web.json_response({
        "messages": messages,
        "usage": _chat_usage_payload(stats),
        "lesson_state": public_lesson_state(lesson_state),
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

    # Гейт лимита и профиль читаем параллельно — независимые запросы.
    stats, user = await asyncio.gather(
        database.get_ai_usage_today(user_id),
        database.get_user(user_id),
    )
    if _ai_daily_limit_reached(stats):
        return web.json_response({
            "reply": _ai_limit_message(),
            "usage": _chat_usage_payload(stats),
            "lesson_state": {},
            "limit_reached": True,
        })

    user_name = user["name"] if user else "друг"

    # Запись сообщения пользователя и продвижение состояния урока — независимые
    # записи в разные таблицы, выполняем параллельно. История — строго после.
    lesson_state = None
    if mode == "voice":
        _, lesson_state = await asyncio.gather(
            database.add_message(user_id, "user", redact_personal_data(text)),
            _advance_voice_lesson_state(user_id, user, "user", text),
        )
    else:
        await database.add_message(user_id, "user", redact_personal_data(text))

    # Берём последние сообщения как контекст для модели
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = mode
    if mode == "voice":
        prompt_context.update(_voice_prompt_context(user, history, lesson_state))
    reply = await chat_reply(history, user_name, age_label, prompt_context)

    if mode == "voice":
        _, lesson_state = await asyncio.gather(
            database.add_message(user_id, "assistant", reply.text),
            _advance_voice_lesson_state(user_id, user, "assistant", reply.text),
        )
    else:
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
        "lesson_state": public_lesson_state(lesson_state),
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
    mode = body.get("mode") if body.get("mode") in {"voice", "word"} else "chat"
    speed = body.get("speed")
    if not text:
        return web.json_response({"error": "Нет текста для озвучки"}, status=400)
    if len(text) > 1200:
        text = text[:1200]

    cache_name = _word_audio_cache_name(text, mode, speed)
    if cache_name:
        try:
            cached = await storage.word_audio_storage.read(cache_name)
        except Exception:  # noqa: BLE001 — нет объекта/файла -> промах кэша
            cached = None
        if cached:
            return web.Response(
                body=cached,
                content_type="audio/mpeg",
                headers={
                    "Cache-Control": "public, max-age=31536000, immutable",
                    "X-Audio-Cache": "hit",
                },
            )

    # Cache miss → stream from OpenAI and tee chunks into the disk cache.
    # Pull the first chunk before prepare() so an immediate failure still returns JSON.
    gen = synthesize_speech_stream(text, mode=mode, speed=speed)
    try:
        first_chunk = await gen.__anext__()
    except StopAsyncIteration:
        log.error("TTS generator yielded no audio for text len=%d", len(text))
        return web.json_response({"error": "Не удалось озвучить ответ: пустой ответ от TTS."}, status=502)
    except Exception as e:
        log.exception("Speech synthesis failed")
        return web.json_response({"error": f"Не удалось озвучить ответ. {public_openai_error(e)}"}, status=502)

    response = web.StreamResponse(headers={
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "X-Audio-Cache": "miss",
    })
    await response.prepare(request)
    buffer = bytearray()
    try:
        if first_chunk:
            buffer.extend(first_chunk)
            await response.write(first_chunk)
        async for chunk in gen:
            buffer.extend(chunk)
            await response.write(chunk)
    except Exception:
        # Headers/200 already sent — end the stream; the client falls back on a short clip.
        log.exception("Speech streaming interrupted")
        await response.write_eof()
        return response

    await response.write_eof()

    # Стоимость списываем только после полностью успешного стрима (не при пустом/обрыве).
    await _record_ai_cost(
        request["tg_user"]["id"],
        OPENAI_TTS_MODEL,
        len(text) / 1000 * OPENAI_TTS_COST_PER_1K_CHARS,
    )

    # Persist to cache only after a full, successful stream.
    if cache_name and buffer:
        try:
            await storage.word_audio_storage.write(cache_name, bytes(buffer))
            if AUDIO_CACHE_DIR is not None:  # eviction только локально (S3 — lifecycle)
                _evict_cache_dir(AUDIO_CACHE_DIR, AUDIO_CACHE_MAX_FILES)
        except Exception:  # noqa: BLE001 — сбой кэша не должен ронять уже отданный ответ
            log.exception("Failed to store word audio cache")

    return response


async def _voice_text_turn_payload(user_id: int, text: str) -> dict:
    # Гейт лимита и профиль читаем параллельно — независимые запросы.
    stats, user = await asyncio.gather(
        database.get_ai_usage_today(user_id),
        database.get_user(user_id),
    )
    if _ai_daily_limit_reached(stats):
        lesson_state = await _ensure_voice_lesson_state(user_id, user)
        return {
            "text": text,
            "reply": _ai_limit_message(),
            "audio_base64": "",
            "audio_content_type": "",
            "audio_error": "",
            "usage": _chat_usage_payload(stats),
            "lesson_state": public_lesson_state(lesson_state),
            "limit_reached": True,
        }
    user_name = user["name"] if user else "друг"

    # Запись реплики пользователя ∥ продвижение урока (разные таблицы).
    _, lesson_state = await asyncio.gather(
        database.add_message(user_id, "user", redact_personal_data(text)),
        _advance_voice_lesson_state(user_id, user, "user", text),
    )
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]

    age_label = _age_label(user["age_group"]) if user else ""
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context.update(_voice_prompt_context(user, history, lesson_state))

    reply = await chat_reply(history, user_name, age_label, prompt_context)
    _, lesson_state = await asyncio.gather(
        database.add_message(user_id, "assistant", reply.text),
        _advance_voice_lesson_state(user_id, user, "assistant", reply.text),
    )
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

    # Аудио инлайн не синтезируем: текст уходит сразу, а озвучку клиент берёт
    # потоково из /api/audio/speech (бинарь + дисковый кэш + прогрессивное
    # воспроизведение). Это убирает ожидание полного MP3 и base64-оверхед.
    return {
        "text": text,
        "reply": reply.text,
        "audio_base64": "",
        "audio_content_type": "",
        "audio_error": "",
        "usage": _chat_usage_payload(stats),
        "lesson_state": public_lesson_state(lesson_state),
    }


async def _voice_unclear_payload(user_id: int, reply_text: str | None = None) -> dict:
    user = await database.get_user(user_id)
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    age_group = _normalized_age_group_for_user(user)
    if reply_text:
        reply = reply_text
    elif age_group == "5_7":
        reply = "Я не очень хорошо услышал. Повтори одно слово, пожалуйста."
    else:
        reply = "Я не очень хорошо услышал. Повтори, пожалуйста, короткой фразой."

    audio_b64 = ""
    audio_error = ""
    try:
        speech = await synthesize_speech(reply, mode="voice")
        audio_b64 = base64.b64encode(speech).decode("ascii")
    except Exception as e:
        log.exception("Unclear voice fallback speech synthesis failed")
        audio_error = public_openai_error(e)

    return {
        "text": "",
        "reply": reply,
        "audio_base64": audio_b64,
        "audio_content_type": "audio/mpeg" if audio_b64 else "",
        "audio_error": audio_error,
        "usage": _chat_usage_payload(await database.get_ai_usage_today(user_id)),
        "lesson_state": public_lesson_state(lesson_state),
        "voice_fallback": "unclear",
    }


async def api_voice_text_turn(request: web.Request):
    """Stable hybrid turn when speech was already transcribed by Realtime."""
    user_id = request["tg_user"]["id"]
    body = await _safe_json(request)
    text = " ".join((body.get("message") or body.get("text") or "").split())
    if not text:
        payload = await _voice_unclear_payload(user_id)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})
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
        payload = await _voice_unclear_payload(user_id)
        return web.json_response(payload, headers={"Cache-Control": "no-store"})
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
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    prompt_context = _realtime_prompt_context(user, history, lesson_state)

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


def _realtime_prompt_context(user, history: list[dict], lesson_state: dict | None = None) -> dict:
    prompt_context = _prompt_context_for_user(user) if user else {}
    prompt_context["mode"] = "voice"
    prompt_context["age_group"] = _normalized_age_group_for_user(user) if user else "8_10"
    prompt_context.update(_voice_prompt_context(user, history, lesson_state))
    return prompt_context


async def api_realtime_token(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    gate_stats = await database.get_ai_usage_today(user_id)
    if _ai_daily_limit_reached(gate_stats):
        return web.json_response({
            "limit_reached": True,
            "error": _ai_limit_message(),
            "usage": _chat_usage_payload(gate_stats),
        }, status=403)
    # Отдельный жёсткий суточный лимит именно на дорогие Realtime-сессии:
    # защита от cost-amplification, не зависит от общего AI_DAILY_MESSAGE_LIMIT.
    if REALTIME_DAILY_SESSION_LIMIT > 0:
        realtime_today = await database.get_model_requests_today(
            user_id, OPENAI_REALTIME_MODEL
        )
        if realtime_today >= REALTIME_DAILY_SESSION_LIMIT:
            return web.json_response({
                "limit_reached": True,
                "error": (
                    "На сегодня голосовые занятия закончились. Возвращайся завтра! "
                    "А пока можно учить слова, проходить тесты и играть."
                ),
                "usage": _chat_usage_payload(gate_stats),
            }, status=429)
    rows = await database.get_recent_messages(user_id, limit=CHAT_HISTORY_LIMIT)
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    age_label = _age_label(user["age_group"]) if user else ""
    lesson_state = await _ensure_voice_lesson_state(user_id, user)
    prompt_context = _realtime_prompt_context(user, history, lesson_state)

    try:
        # Общий бюджет на токен (включая retry внутри): не даём ребёнку висеть
        # на застывшем экране ~50с при сбоях OpenAI.
        token_coro = create_realtime_client_secret(
            user_id=user_id,
            user_name=user["name"] if user else "друг",
            age_label=age_label,
            prompt_context=prompt_context,
        )
        if REALTIME_TOKEN_TIMEOUT_SEC > 0:
            token = await asyncio.wait_for(token_coro, timeout=REALTIME_TOKEN_TIMEOUT_SEC)
        else:
            token = await token_coro
    except asyncio.TimeoutError:
        log.warning("Realtime token timed out after %ss", REALTIME_TOKEN_TIMEOUT_SEC)
        return web.json_response(
            {"error": "Голос пока не отвечает. Попробуй ещё раз через минутку."},
            status=504,
        )
    except Exception as e:
        log.exception("Realtime token setup failed: %s", e)
        return web.json_response({"error": public_openai_error(e)}, status=502)

    # Учитываем старт Realtime-сессии: видимость расходов в админке и заодно
    # этот ход считается в дневной freemium-лимит (раньше голос его обходил).
    await _record_ai_cost(user_id, OPENAI_REALTIME_MODEL, OPENAI_REALTIME_SESSION_COST)
    return web.json_response(token, headers={"Cache-Control": "no-store"})


async def api_realtime_log(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    body = await _safe_json(request)
    role = "assistant" if body.get("role") == "assistant" else "user"
    content = " ".join(str(body.get("content") or "").split())
    if not content:
        return web.json_response({"ok": True})
    if len(content) > 1000:
        content = content[:1000]
    stored_content = redact_personal_data(content) if role == "user" else content
    await database.add_message(user_id, role, stored_content)
    lesson_state = await _advance_voice_lesson_state(user_id, user, role, content)
    return web.json_response({
        "ok": True,
        "lesson_state": public_lesson_state(lesson_state),
    })


async def api_chat_reset(request: web.Request):
    user_id = request["tg_user"]["id"]
    await database.clear_conversation(user_id)
    await database.clear_voice_lesson_state(user_id)
    return web.json_response({"ok": True})


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
