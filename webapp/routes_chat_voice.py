"""ИИ-репетитор: чат, озвучка/распознавание, гибридный голосовой ход и
Realtime-сессии (вынесено из webapp/server.py, шаг 3e-3).

Маршруты: /api/chat/*, /api/audio/*, /api/voice/*, /api/realtime/*.

Зависимости направлены только «вниз» (config, database, storage, formatters,
payload_builders, http_utils, lesson_engine, openai_service, voice_context) —
модуль НЕ импортирует server.py, циклов нет. server.py реэкспортирует имена:
регистрация маршрутов и импорты в тестах работают как раньше; патчи целятся в
`webapp.routes_chat_voice.*`.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os

from aiohttp import web

import database
from config import (
    AI_DAILY_MESSAGE_LIMIT,
    OPENAI_DAILY_COST_LIMIT_USD,
    CHAT_HISTORY_LIMIT,
    OPENAI_REALTIME_MODEL,
    OPENAI_REALTIME_SESSION_COST,
    OPENAI_TTS_COST_PER_1K_CHARS,
    OPENAI_TTS_MODEL,
    REALTIME_DAILY_SESSION_LIMIT,
    REALTIME_TOKEN_TIMEOUT_SEC,
)
from webapp import storage
from webapp.formatters import _age_label, _normalized_age_group_for_user
from webapp.http_utils import _current_user_or_404, _safe_json
from webapp.lesson_engine import public_lesson_state
from webapp.openai_service import (
    chat_reply,
    create_realtime_call,
    create_realtime_client_secret,
    public_openai_error,
    redact_personal_data,
    synthesize_speech,
    synthesize_speech_stream,
    transcribe_audio,
)
from webapp.payload_builders import _chat_usage_payload
from webapp.storage import _evict_cache_dir
from webapp.voice_context import (
    _advance_voice_lesson_state,
    _ensure_voice_lesson_state,
    _prompt_context_for_user,
    _realtime_prompt_context,
    _voice_prompt_context,
)

log = logging.getLogger(__name__)

# Каталог кэша озвучки — из слоя хранилища (как в word_payloads: значение
# производное от storage, не разделяемое состояние). Для S3/R2 — None.
AUDIO_CACHE_DIR = getattr(storage.word_audio_storage, "base_dir", None)
# Кэши на эфемерном диске Render не должны расти бесконечно (QA-аудит).
AUDIO_CACHE_MAX_FILES = int(os.getenv("AUDIO_CACHE_MAX_FILES", "4000"))
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_SDP_BYTES = 16 * 1024  # реальный WebRTC SDP < 4 КБ; жёсткий предел тела


# ---------- Кэш озвучки и валидация аудио ----------

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


# ---------- Учёт расходов и дневной лимит AI ----------

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


async def _ai_budget_exceeded() -> bool:
    """True, если суммарные расходы OpenAI за сегодня превысили глобальный потолок
    (OPENAI_DAILY_COST_LIMIT_USD). Защита от runaway-затрат по всем пользователям.
    Сбой подсчёта не блокирует пользователя (fail-open: учёт ≠ доступность)."""
    if OPENAI_DAILY_COST_LIMIT_USD <= 0:
        return False
    try:
        total = await database.get_ai_cost_today_total()
    except Exception:
        log.exception("Не удалось посчитать суточные расходы OpenAI")
        return False
    if total >= OPENAI_DAILY_COST_LIMIT_USD:
        log.critical(
            "Достигнут суточный потолок расходов OpenAI: $%.2f >= $%.2f — AI приостановлен",
            total, OPENAI_DAILY_COST_LIMIT_USD,
        )
        return True
    return False


# ---------- API: чат с репетитором ----------

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
    if _ai_daily_limit_reached(stats) or await _ai_budget_exceeded():
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


# ---------- API: озвучка и распознавание ----------

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

    # Cache miss → новый синтез тратит OpenAI. При превышении суточного бюджета
    # не запускаем синтез (кэш-озвучка выше уже отдана бесплатно — слова учить можно).
    if await _ai_budget_exceeded():
        return web.json_response({"error": _ai_limit_message()}, status=429)

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


# ---------- API: гибридный голосовой ход ----------

async def _voice_text_turn_payload(user_id: int, text: str) -> dict:
    # Гейт лимита и профиль читаем параллельно — независимые запросы.
    stats, user = await asyncio.gather(
        database.get_ai_usage_today(user_id),
        database.get_user(user_id),
    )
    if _ai_daily_limit_reached(stats) or await _ai_budget_exceeded():
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


# ---------- API: Realtime (WebRTC) ----------

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


async def api_realtime_token(request: web.Request):
    user_id = request["tg_user"]["id"]
    user = await _current_user_or_404(request)
    gate_stats = await database.get_ai_usage_today(user_id)
    if _ai_daily_limit_reached(gate_stats) or await _ai_budget_exceeded():
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
