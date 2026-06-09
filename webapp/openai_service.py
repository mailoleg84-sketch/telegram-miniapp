"""Обёртка над OpenAI API: ИИ-репетитор английского."""
import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging
import re

import aiohttp
from openai import APIConnectionError, AuthenticationError, AsyncOpenAI, BadRequestError, RateLimitError

from config import (
    CHAT_MAX_TOKENS,
    OPENAI_INPUT_COST_PER_1M,
    OPENAI_API_KEY,
    OPENAI_IMAGE_FORMAT,
    OPENAI_IMAGE_MAX_RETRIES,
    OPENAI_IMAGE_MODEL,
    OPENAI_IMAGE_QUALITY,
    OPENAI_IMAGE_SIZE,
    OPENAI_IMAGE_VISION_MODEL,
    OPENAI_MODEL,
    OPENAI_OUTPUT_COST_PER_1M,
    OPENAI_PROMPT_FOR_VOICE,
    OPENAI_PROMPT_ID,
    OPENAI_PROMPT_VERSION,
    OPENAI_REALTIME_MODEL,
    OPENAI_REALTIME_REASONING_EFFORT,
    OPENAI_REALTIME_TRANSCRIBE_MODEL,
    OPENAI_REALTIME_VOICE,
    OPENAI_REASONING_EFFORT,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TRANSCRIBE_MODEL,
    OPENAI_VOICE_REASONING_EFFORT,
    OPENAI_VOICE_TTS_VOICE,
    REALTIME_AGE_PROFILES,
    age_group_from_age,
    TUTOR_CORRECTION_MODE,
    TUTOR_DEFAULT_LEVEL,
    TUTOR_DEFAULT_STYLE,
    TUTOR_DEFAULT_TOPICS,
    TUTOR_LANGUAGE_BALANCE,
    VOICE_MAX_TOKENS,
)

log = logging.getLogger(__name__)
VOICE_REPLY_MAX_CHARS = 320
VOICE_REPLY_MAX_SENTENCES = 3
_DUPLICATE_GLOSS_RE = re.compile(r"\b([A-Za-z][A-Za-z' -]{0,40}?)\s+[—-]\s+\1\s+[—-]\s+", re.IGNORECASE)

_client: AsyncOpenAI | None = None
if OPENAI_API_KEY:
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    log.info("OpenAI API key configured")
else:
    log.warning("OPENAI_API_KEY не задан — режим репетитора работать не будет.")


def openai_config_status() -> dict:
    """Safe diagnostics without exposing the secret."""
    return {
        "configured": bool(OPENAI_API_KEY),
        "model": OPENAI_MODEL,
        "tts_model": OPENAI_TTS_MODEL,
        "tts_voice": OPENAI_TTS_VOICE,
        "voice_tts_voice": OPENAI_VOICE_TTS_VOICE,
        "realtime_model": OPENAI_REALTIME_MODEL,
        "realtime_voice": OPENAI_REALTIME_VOICE,
        "realtime_transcribe_model": OPENAI_REALTIME_TRANSCRIBE_MODEL,
        "realtime_reasoning_effort": OPENAI_REALTIME_REASONING_EFFORT,
        "image_model": OPENAI_IMAGE_MODEL,
        "image_size": OPENAI_IMAGE_SIZE,
        "image_quality": OPENAI_IMAGE_QUALITY,
        "image_format": OPENAI_IMAGE_FORMAT,
        "image_vision_model": OPENAI_IMAGE_VISION_MODEL,
        "prompt_id_configured": bool(OPENAI_PROMPT_ID),
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_for_voice": OPENAI_PROMPT_FOR_VOICE,
        "voice_reasoning_effort": OPENAI_VOICE_REASONING_EFFORT,
        "voice_max_tokens": VOICE_MAX_TOKENS,
    }


def public_openai_error(error: Exception) -> str:
    """Returns a child-safe error message without leaking secrets or raw provider payloads."""
    message = str(error)
    if "billing_hard_limit_reached" in message or "Billing hard limit has been reached" in message:
        return "В OpenAI достигнут лимит расходов. Увеличьте hard limit в Billing, затем нажмите «Загрузить картинку ещё раз»."
    if "insufficient_quota" in message:
        return "У OpenAI закончилась квота или не включена оплата. Проверьте Billing и Limits."
    if isinstance(error, AuthenticationError):
        return "Репетитор пока не настроен. Родителю нужно обновить ключ OpenAI."
    if isinstance(error, RateLimitError):
        return "OpenAI временно ограничил запросы. Попробуй чуть позже."
    if isinstance(error, APIConnectionError):
        return "Не удалось подключиться к OpenAI. Попробуй еще раз через минуту."
    return "Не удалось получить ответ от репетитора. Попробуй еще раз."


SYSTEM_PROMPT = """Ты — живой, добрый AI-репетитор английского для ребенка по имени {name}.

Возрастная группа ученика: {age_label}.

Твоя задача — вести голосовой диалог так, чтобы ребенку было легко, интересно и не страшно ошибаться.

Главные правила:
- Всегда определяй язык последней реплики ребенка.
- Если ребенок говорит или пишет по-русски, отвечай по-русски, коротко объясняй смысл и давай 1–2 очень простые английские фразы для повторения.
- Если ребенок говорит или пишет по-английски, отвечай в основном по-английски, но сложные объяснения и исправления давай по-русски.
- Если ребенок говорит «не понимаю», «что делать», «переведи», присылает «?» или молчит/путается, сразу переходи на русский и помогай.
- Не спрашивай, нужен ли русский язык. Если видишь, что ребенку трудно, просто помоги по-русски.
- Отвечай очень коротко для голосового режима: 1–3 коротких предложения.
- Давай только одно задание за раз.
- Не задавай больше одного вопроса в конце ответа.
- Если ребенок ошибся, не исправляй всё сразу: выбери одну главную ошибку.
- Если ребенок молчит, отвечает односложно или устал, предложи более легкое задание или выбор из двух вариантов.
- В конце почти всегда задавай один простой вопрос или предлагай выбор из 2 тем.
- Темы должны быть детскими: животные, цвета, еда, школа, игры, спорт, путешествия, сказочная история, загадка, мини-квест.
- Для детей 5–10 лет используй самые простые слова, игру, похвалу и повторение.
- Для 11–18 лет можно чуть взрослее: диалоги, школа, хобби, путешествия, экзамены, но без взрослых или опасных тем.
- Исправляй ошибки мягко: сначала похвали, потом дай правильный вариант.
- Говори тепло, понятно и коротко, как живой репетитор в голосовом разговоре.
- Не используй markdown, таблицы, длинные списки и нумерацию, если ребенок не просит подробный урок.
- Веди не лекцию, а короткий цикл: услышал ребенка, ответил по сути, дал одну полезную фразу, попросил ребенка сказать или выбрать что-то маленькое.
- Используй повторение с интервалом: иногда возвращай одно слово или фразу из недавнего разговора, но не превращай каждый ответ в тест.
- Не начинай каждый раз с animals, colors, game или story. Меняй активность: роль, мини-квест, угадай слово, вопрос про день, короткая сценка, повторение фразы.

Если ребенок просто здоровается или не знает, что сказать, предложи 2–3 разные безопасные темы из текущего контекста и начни легкую игру. Не повторяй одну и ту же тему подряд."""


VOICE_TTS_INSTRUCTIONS = (
    "Говори как живой внимательный репетитор рядом с ребенком: естественно, тепло, "
    "разговорно, с мягкой интонацией и короткими паузами. Не как диктор, не как робот, "
    "не театрально и не слишком бодро. Русский произноси натурально. Английские слова "
    "произноси с чистым английским произношением, даже внутри русской фразы. "
    "Фразы короткие, голос спокойный, с легкой улыбкой."
)


@dataclass(frozen=True)
class ChatReply:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class VocabularyImageResult:
    image_bytes: bytes
    content_type: str
    model: str
    prompt: str
    review: dict
    generation_status: str
    attempts: int = 1


def _default_image_review(reason: str = "") -> dict:
    return {
        "is_safe": True,
        "has_text": False,
        "supports_meaning": True,
        "ambiguity_level": "unknown",
        "should_regenerate": False,
        "reason": reason or "Vision review was not available.",
    }


def _extract_json_object(text: str) -> dict:
    clean_text = (text or "").strip()
    try:
        return json.loads(clean_text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", clean_text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def _normalized_image_format() -> str:
    image_format = (OPENAI_IMAGE_FORMAT or "png").lower()
    return image_format if image_format in {"png", "jpeg", "webp"} else "png"


def _image_content_type(image_format: str) -> str:
    return {
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(image_format, "image/png")


def _image_generation_prompt(visual: dict, retry_reason: str = "") -> str:
    word = str(visual.get("word") or "").strip()
    translation = str(visual.get("translation") or "").strip()
    visual_type = str(visual.get("visual_type") or "situation").strip()
    prompt = str(visual.get("image_prompt") or "").strip()
    example = str(visual.get("example_sentence") or visual.get("example") or "").strip()
    simple_meaning = str(visual.get("simple_meaning") or "").strip()
    russian_hint = str(visual.get("russian_hint") or "").strip()
    retry_note = (
        f"\nPrevious review problem to fix: {retry_reason[:280]}"
        if retry_reason
        else ""
    )
    return f"""Create one high-quality educational vocabulary card illustration.

English word: {word}
Russian translation: {translation}
Visual type: {visual_type}
Example sentence: {example}
Simple meaning: {simple_meaning}
Russian hint: {russian_hint}

Scene prompt:
{prompt}

Important:
- The image must contain no text, no letters, no captions, no labels, no logo, and no watermark.
- For complex words, the image is only a memory cue. It must support the example and meaning, not replace the translation.
- Keep it child-safe, friendly, non-scary, and suitable for children 5-18.
- Use one consistent premium EdTech illustration style.
- Avoid generic portraits for abstract words; show a concrete situation instead.{retry_note}"""


async def evaluate_vocabulary_image(image_bytes: bytes, visual: dict) -> dict:
    """Checks whether a generated vocabulary image is safe and useful enough."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    image_format = _normalized_image_format()
    data_url = (
        f"data:{_image_content_type(image_format)};base64,"
        + base64.b64encode(image_bytes).decode("ascii")
    )
    word = str(visual.get("word") or "").strip()
    payload = {
        "word": word,
        "translation": str(visual.get("translation") or ""),
        "example_sentence": str(visual.get("example_sentence") or ""),
        "simple_meaning": str(visual.get("simple_meaning") or ""),
        "visual_type": str(visual.get("visual_type") or ""),
    }
    response = await _client.responses.create(
        model=OPENAI_IMAGE_VISION_MODEL,
        input=[{
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": (
                        "Does this image help a child understand and remember the English word "
                        f"{word!r} in the context of this card?\n\n"
                        f"Card JSON:\n{json.dumps(payload, ensure_ascii=False)}\n\n"
                        "Evaluate:\n"
                        "1. Is the image child-safe?\n"
                        "2. Is there any text, letters, logos, or watermark?\n"
                        "3. Does the image support the meaning?\n"
                        "4. Is the image too ambiguous?\n"
                        "5. Should it be regenerated?\n\n"
                        "Return only JSON with keys: is_safe, has_text, supports_meaning, "
                        "ambiguity_level, should_regenerate, reason."
                    ),
                },
                {"type": "input_image", "image_url": data_url},
            ],
        }],
        instructions="You are a strict quality checker for child-safe EdTech vocabulary images. Return valid JSON only.",
        max_output_tokens=260,
    )
    review = _extract_json_object(response.output_text or "")
    if not review:
        review = _default_image_review("Vision model did not return parseable JSON.")
    review["is_safe"] = bool(review.get("is_safe", True))
    review["has_text"] = bool(review.get("has_text", False))
    review["supports_meaning"] = bool(review.get("supports_meaning", True))
    review["should_regenerate"] = bool(review.get("should_regenerate", False))
    review["ambiguity_level"] = str(review.get("ambiguity_level") or "unknown")
    review["reason"] = str(review.get("reason") or "")
    return review


def _review_accepts_image(review: dict) -> bool:
    if not review.get("is_safe", True):
        return False
    if review.get("has_text", False):
        return False
    if review.get("should_regenerate", False) and not review.get("supports_meaning", True):
        return False
    return True


async def generate_vocabulary_image(visual: dict, user_id: int | str) -> VocabularyImageResult:
    """Generates one vocabulary image and runs a vision quality check."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    image_format = _normalized_image_format()
    content_type = _image_content_type(image_format)
    retry_reason = ""
    last_bytes = b""
    last_review: dict = {}
    max_attempts = max(1, min(3, 1 + OPENAI_IMAGE_MAX_RETRIES))

    for attempt in range(1, max_attempts + 1):
        prompt = _image_generation_prompt(visual, retry_reason=retry_reason)
        request = {
            "model": OPENAI_IMAGE_MODEL,
            "prompt": prompt,
            "size": OPENAI_IMAGE_SIZE,
            "quality": OPENAI_IMAGE_QUALITY,
            "output_format": image_format,
            "n": 1,
            "user": _safety_identifier(user_id),
        }
        if not OPENAI_IMAGE_MODEL.startswith("gpt-image"):
            request["response_format"] = "b64_json"
        try:
            response = await _client.images.generate(**request)
        except BadRequestError:
            request.pop("quality", None)
            response = await _client.images.generate(**request)

        item = response.data[0] if getattr(response, "data", None) else None
        b64_json = getattr(item, "b64_json", "") if item else ""
        if not b64_json:
            raise RuntimeError("OpenAI image generation returned no image data")
        image_bytes = base64.b64decode(b64_json)
        last_bytes = image_bytes
        try:
            review = await evaluate_vocabulary_image(image_bytes, visual)
        except Exception as exc:
            log.warning("Vocabulary image vision review failed: %s", exc)
            review = _default_image_review(str(exc)[:180])
        last_review = review
        if _review_accepts_image(review):
            return VocabularyImageResult(
                image_bytes=image_bytes,
                content_type=content_type,
                model=OPENAI_IMAGE_MODEL,
                prompt=prompt,
                review=review,
                generation_status="generated" if not review.get("should_regenerate") else "needs_review",
                attempts=attempt,
            )
        retry_reason = str(review.get("reason") or "The image failed quality review.")

    return VocabularyImageResult(
        image_bytes=last_bytes,
        content_type=content_type,
        model=OPENAI_IMAGE_MODEL,
        prompt=_image_generation_prompt(visual, retry_reason=retry_reason),
        review=last_review or _default_image_review("Image failed quality review."),
        generation_status="failed",
        attempts=max_attempts,
    )


def _supports_reasoning(model: str) -> bool:
    return model.startswith(("gpt-5", "o1", "o3", "o4"))


def _usage_int(usage, field: str) -> int:
    if usage is None:
        return 0
    value = getattr(usage, field, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(field)
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _clamp_speech_speed(value: float | int | str | None, default: float) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        speed = default
    return round(max(0.75, min(1.15, speed)), 2)


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = input_tokens * OPENAI_INPUT_COST_PER_1M / 1_000_000
    output_cost = output_tokens * OPENAI_OUTPUT_COST_PER_1M / 1_000_000
    return round(input_cost + output_cost, 6)


def _has_cyrillic(text: str) -> bool:
    return any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in text or "")


def _has_latin(text: str) -> bool:
    return any("a" <= ch.lower() <= "z" for ch in text or "")


def _last_user_text(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _last_language(text: str) -> str:
    if _has_cyrillic(text):
        return "russian"
    if _has_latin(text):
        return "english"
    return "unknown"


def _interaction_mode(prompt_context: dict | None) -> str:
    return "voice" if (prompt_context or {}).get("mode") == "voice" else "chat"


def _cut_at_sentence_boundary(text: str, max_chars: int) -> str:
    """Keeps TTS text complete enough to avoid chopping a word or clause mid-speech."""
    clean_text = " ".join((text or "").split())
    if len(clean_text) <= max_chars:
        return clean_text
    cut = clean_text[:max_chars].rstrip()
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"), cut.rfind("…"))
    if boundary >= max_chars * 0.55:
        return cut[:boundary + 1].strip()
    comma = max(cut.rfind(","), cut.rfind(";"), cut.rfind(":"))
    if comma >= max_chars * 0.65:
        return cut[:comma].strip() + "."
    space = cut.rfind(" ")
    if space > 0:
        return cut[:space].strip() + "."
    return cut.strip()


def _voice_sentence_parts(text: str) -> list[str]:
    clean_text = " ".join((text or "").split())
    if not clean_text:
        return []
    return [
        part.strip()
        for part in re.findall(r".+?(?:[.!?…]+(?=\s|$)|$)", clean_text)
        if part.strip()
    ]


def _trim_voice_turn(
    text: str,
    max_chars: int = VOICE_REPLY_MAX_CHARS,
    max_sentences: int = VOICE_REPLY_MAX_SENTENCES,
) -> str:
    """Keeps a spoken turn brief while preserving complete sentences."""
    cleaned = _clean_voice_reply(text)
    parts = _voice_sentence_parts(cleaned)
    if len(parts) > max_sentences:
        cleaned = " ".join(parts[:max_sentences])
    return _cut_at_sentence_boundary(cleaned, max_chars)


def _voice_reply_quality_flags(text: str, last_user_text: str = "") -> list[str]:
    """Returns lightweight quality warnings without making another model call."""
    cleaned = " ".join((text or "").split())
    flags: list[str] = []
    if len(cleaned) > VOICE_REPLY_MAX_CHARS:
        flags.append("too_long")
    if len(_voice_sentence_parts(cleaned)) > VOICE_REPLY_MAX_SENTENCES:
        flags.append("too_many_sentences")
    if re.search(r"\b(?:pochti|khorosho|molodets|privet|spasibo)\b", cleaned, re.IGNORECASE):
        flags.append("russian_transliteration")
    if re.search(
        r"\b(?:какой|какая|какое|какие|твой|твоя|твоё|мой|моя|выбери|скажи)\s+[a-z][a-z'-]*\b",
        cleaned,
        re.IGNORECASE,
    ):
        flags.append("mixed_russian_grammar")
    if re.search(r":\s*[a-z][a-z'-]*\s+(?:or|или)\s+[a-z][a-z'-]*\?", cleaned, re.IGNORECASE):
        flags.append("mixed_russian_grammar")
    if re.search(
        r"\b(?:любишь|выбираешь|хочешь|нравится)\s+[a-z][a-z'-]*(?:\s+[a-z][a-z'-]*)*\s+(?:or|или)\s+[a-z][a-z'-]*\b",
        cleaned,
        re.IGNORECASE,
    ):
        flags.append("mixed_russian_grammar")
    if re.search(r"\b(?:great|nice|cool|wow|awesome)!\s+[a-z][a-z'-]*[.!?](?:\s|$)", cleaned, re.IGNORECASE):
        flags.append("unnatural_fragment")
    if re.search(r"\bi like\s+[a-z][a-z'-]*(?:s)?\s+in the\s+(?:morning|evening|afternoon|night)\b", cleaned, re.IGNORECASE):
        flags.append("unnatural_example")
    sentence_parts = _voice_sentence_parts(cleaned)
    if _has_cyrillic(last_user_text) and sentence_parts:
        final_sentence = sentence_parts[-1]
        if final_sentence.endswith("?") and _has_latin(final_sentence) and not _has_cyrillic(final_sentence):
            flags.append("russian_turn_ends_in_english")
    next_step_markers = (
        "?", "скажи", "попробуй", "повтори", "выбери", "представь", "назови",
        "try", "say", "choose", "repeat", "tell me", "your turn", "answer",
    )
    if cleaned and not any(marker in cleaned.lower() for marker in next_step_markers):
        flags.append("missing_next_step")
    return flags


def _finalize_voice_reply(text: str, last_user_text: str = "") -> str:
    flags = _voice_reply_quality_flags(text, last_user_text)
    finalized = _trim_voice_turn(text)
    flags = sorted(set(flags + _voice_reply_quality_flags(finalized, last_user_text)))
    if flags:
        log.warning("Voice reply quality flags: %s", ", ".join(flags))
    return finalized


def _needs_russian_repair(last_user_text: str, reply_text: str) -> bool:
    if not _has_cyrillic(last_user_text) or not reply_text.strip():
        return False
    if not _has_cyrillic(reply_text):
        return True
    repair_flags = set(_voice_reply_quality_flags(reply_text, last_user_text))
    return bool(repair_flags & {"mixed_russian_grammar", "russian_turn_ends_in_english"})


_GUARD_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)

# Структурные маркеры ролевой инъекции (служебные токены чат-форматов).
_INJECTION_TOKEN_RE = re.compile(
    r"<\|.*?\|>"                          # <|system|>, <|im_start|>
    r"|<<\s*/?\s*sys\s*>>"                # <<SYS>>, <</SYS>>
    r"|\[/?inst\]"                        # [INST], [/INST]
    r"|\[/?(?:system|assistant|user)\]"   # [system], [/system]
    r"|#{2,}\s*(?:system|instruction)",   # ## system
    re.IGNORECASE,
)

# Компактные маркеры (после lower + leet + удаления пробелов/дефисов) — ловят
# обходы вида "а-п-и ключ", "0penai key", "i g n o r e previous instructions".
_GUARD_SECRET_MARKERS = (
    "apikey", "openaikey", "openaiapi", "secretkey", "accesstoken", "openaitoken",
    "апиключ", "ключапи", "секретныйключ",
)
_GUARD_PROMPT_MARKERS = (
    "systemprompt", "системныйпромпт", "твоиинструкции", "покажипромпт",
    "покажисистемный", "ignoreprevious", "ignoreallprevious", "ignoreinstructions",
    "disregardprevious", "forgetprevious", "forgetyourinstructions",
    "revealyourprompt", "showsystemprompt", "yoursystemprompt",
    "забудьинструкции", "игнорируйинструкции", "jailbreak", "developermode",
)


def _guard_squeeze(text: str) -> str:
    """lower + leet-подмены + удаление всех неалфанумерик-разделителей."""
    lowered = (text or "").lower().translate(_GUARD_LEET)
    return re.sub(r"[^a-zа-яё0-9]", "", lowered)


def neutralize_injection(text: str) -> str:
    """Обезвреживает служебные токены ролевой инъекции (<|system|>, [/INST],
    <<SYS>>, [system] и т.п.) перед отправкой модели/сохранением. Обычный
    детский текст не трогает."""
    if not text:
        return text
    return _INJECTION_TOKEN_RE.sub("[фильтр]", text)


def _sanitize_history_for_model(history: list[dict]) -> list[dict]:
    """Копия истории с обезвреженными токенами инъекции в content."""
    return [
        {"role": m.get("role"), "content": neutralize_injection(str(m.get("content") or ""))}
        for m in history
    ]


def _safety_guard_reply(last_user_text: str) -> str | None:
    text = " ".join((last_user_text or "").split())
    normalized = text.lower()
    if not normalized:
        return None
    squeezed = _guard_squeeze(text)

    wants_secret = (
        ("api" in normalized and ("ключ" in normalized or "key" in normalized))
        or "openai key" in normalized
        or "секрет" in normalized and ("ключ" in normalized or "токен" in normalized)
        or "token" in normalized and "openai" in normalized
        or any(marker in squeezed for marker in _GUARD_SECRET_MARKERS)
    )
    wants_prompt = (
        "system prompt" in normalized
        or "системн" in normalized and "пром" in normalized
        or "ignore previous instructions" in normalized
        or "предыдущ" in normalized and "инструкц" in normalized
        or bool(_INJECTION_TOKEN_RE.search(text))
        or any(marker in squeezed for marker in _GUARD_PROMPT_MARKERS)
    )
    shares_personal_data = (
        "мой адрес" in normalized
        or "мой телефон" in normalized
        or "мой номер" in normalized
        or "my address" in normalized
        or "my phone" in normalized
        or re.search(r"\+?\d[\d\s().-]{7,}\d", normalized)
    )
    asks_adult_topic = (
        "взрослые темы" in normalized
        or "adult topic" in normalized
        or "18+" in normalized
    )

    if shares_personal_data:
        return (
            "Не отправляй адрес, телефон или личные данные в чат. "
            "Если это важно, покажи сообщение родителю. Давай лучше потренируем безопасную фразу: I need help — мне нужна помощь."
        )
    if wants_secret:
        return (
            "Я не могу показывать или искать API-ключи и секреты. "
            "Такие вещи должен смотреть только взрослый владелец аккаунта. Давай вернемся к английскому."
        )
    if wants_prompt:
        return (
            "Я не раскрываю скрытые инструкции. "
            "Я здесь, чтобы помогать с английским. Выбери: игра или короткая фраза?"
        )
    if asks_adult_topic:
        return (
            "Эту тему мы не обсуждаем. "
            "Давай выберем безопасную тему для английского: игры, школа или еда?"
        )
    return None


_PII_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{7,}\d")
_PII_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PII_ADDRESS_RE = re.compile(
    r"(мо[йя]\s+адрес|наш\s+адрес|по\s+адресу|my\s+address|home\s+address)(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def redact_personal_data(text: str) -> str:
    """Маскирует личные данные ребёнка перед сохранением в БД (QA H1).

    Телефоны и email маскируются точечно. После явного маркера адреса
    («мой адрес», «my address») всё содержимое заменяется на [скрыт], но сам
    маркер сохраняется — чтобы детерминированный safety-guard всё ещё узнал
    намерение и мягко отговорил ребёнка. История читается моделью уже из БД,
    поэтому в OpenAI исходные данные тоже не уходят.
    """
    if not text:
        return text
    redacted = _PII_PHONE_RE.sub("[номер скрыт]", text)
    redacted = _PII_EMAIL_RE.sub("[email скрыт]", redacted)
    redacted = _PII_ADDRESS_RE.sub(lambda m: f"{m.group(1)} [скрыт]", redacted)
    return redacted


def _clean_voice_reply(text: str) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = _DUPLICATE_GLOSS_RE.sub(r"\1 — ", cleaned)
    transliteration_replacements = {
        "Pochti": "Почти",
        "Khorosho": "Хорошо",
        "Molodets": "Молодец",
        "Privet": "Привет",
        "Spasibo": "Спасибо",
    }
    for source, target in transliteration_replacements.items():
        cleaned = re.sub(rf"\b{source}\b", target, cleaned, flags=re.IGNORECASE)
    if _has_cyrillic(cleaned):
        cleaned = cleaned.replace("Choose:", "Выбери:")
    for marker in ("🙂", "😀", "😄", "😊", "😉", "👍", "🎉", "✨"):
        cleaned = cleaned.replace(marker, "")
    for marker in ("**", "__", "`"):
        cleaned = cleaned.replace(marker, "")
    return " ".join(cleaned.split())


def _looks_like_legacy_voice_template(text: str) -> bool:
    normalized = " ".join((text or "").split()).lower()
    if not normalized:
        return False
    legacy_markers = (
        "repeat:",
        "say:",
        "good! say",
        "nice! say",
        "repeat ",
        "in russian:",
    )
    return any(marker in normalized for marker in legacy_markers)


def _clean_history_for_mode(history: list[dict], mode: str) -> list[dict]:
    if mode != "voice":
        return history
    cleaned: list[dict] = []
    for message in history:
        role = message.get("role")
        content = str(message.get("content") or "")
        if role == "assistant" and _looks_like_legacy_voice_template(content):
            continue
        cleaned.append(message)
    return cleaned[-8:]


def _voice_module_prompt(
    user_name: str,
    age: str,
    level: str,
    goal: str,
    topics: str,
    topic_suggestions: str,
    avoid_topics: str,
    recent_user_messages: str,
    recent_assistant_messages: str,
    last_user_text: str,
    language: str,
    lesson_focus: str,
    activity_menu: str,
    lesson_loop: str,
) -> str:
    return f"""Ты — живой голосовой репетитор английского для ребенка. Отвечай быстро, тепло, по теме и только финальной устной репликой.

Контекст: имя {user_name or "друг"}; возраст {age}; уровень {level}; цель {goal}; интересы {topics}; свежие темы {topic_suggestions}; язык последней реплики {language}.
Последняя реплика ребенка: {last_user_text or "пусто"}.
Текущая линия урока: {lesson_focus}.
Недавно ребенок говорил: {recent_user_messages}. Ты отвечал: {recent_assistant_messages}.

Главный принцип:
Сначала будь человеком, потом учителем. Услышь смысл и настроение ребенка, ответь на это, но каждая реплика должна вести обучение английскому: маленькая фраза, слово, исправление, выбор или мини-задание.

Контракт каждого голосового хода:
1) Коротко и естественно отреагируй именно на слова ребенка.
2) Дай только одну полезную подсказку, модель фразы или мягкое исправление.
3) Закончи одним вопросом или микро-заданием, которое прямо продолжает слова ребенка.
Это три смысловых шага, а не обязательные три предложения. Обычно достаточно 2-3 коротких предложений. Никогда не делай больше трех.
В каждом ходе обязательно должен быть обучающий элемент английского: одно слово, одна фраза, одно исправление, выбор из двух вариантов или микро-практика. Простая болтовня без обучения запрещена.

Жесткие правила:
- Максимум 3 коротких предложения и 220 символов. Без markdown, списков, анализа и лекций.
- Сначала ответь на реальный смысл последней реплики. Не уводи в заготовленную тему.
- Финальный вопрос или задание должен прямо следовать из последней реплики ребенка. Не заканчивай случайным выбором только ради вопроса.
- Когда тема уже выбрана, не предлагай меню тем и не перечисляй другие темы. Продолжай текущую живую сцену.
- Не выдавай обрывки вроде "Great! song." Скажи законченную естественную мысль: "Great choice! What song do you like?"
- Когда исправляешь фразу ребенка, не придумывай случайное продолжение ради грамматики. Модель должна быть естественной и близкой к словам ребенка: "I like cats", "I like Minecraft", "I play football". Не говори странные фразы вроде "I like cats in the morning".
- Никогда не пиши русские слова латиницей: не "Pochti", а "Почти". Не смешивай английское слово с русской грамматикой: не "Какой song?", а "Какая песня тебе нравится?"
- Не просто болтай. В каждом ответе должен быть учебный шаг: model, correction, practice, choice или review. Исключение: ребенок явно просит “по-русски без английского” или говорит, что не понимает — тогда сначала объясни по-русски, но все равно мягко верни к обучению следующим ходом.
- Если ответ получился просто разговорным, перепиши его в учебный ход: реакция + одна английская польза + один следующий шаг.
- Не меняй тему сам по времени. Продолжай текущую линию урока и мини-сцену, пока ребенок сам не попросит другую тему, не устанет или не закончит задание.
- Не используй markdown: никаких **звездочек**, списков, заголовков, кавычек-оформлений.
- Не используй команды “Say:” и “Repeat:”. Если исправляешь, скажи по-человечески: “лучше так: ...”
- Русский запрос -> отвечай по-русски и дай один маленький учебный шаг по английскому, если ребенок не просил “без английского”.
- После русской реплики финальный вопрос или задание тоже должен быть по-русски. Английским может быть только одна отдельная учебная фраза.
- Не вставляй английские варианты внутрь русского вопроса: не "Что любишь: music or songs?", а "Что ты любишь слушать: музыку или песни?"
- Не говори "любишь games или no?". Скажи по-русски: "Тебе нравятся игры или нет?"
- “не понимаю”, “что?”, “переведи”, “помоги”, “?” -> сначала по-русски объясни спокойно. Потом дай один очень легкий шаг, например выбор из двух слов.
- Если в русском ответе есть английское слово, сразу дай понятный смысл рядом: “good — хорошо”, “boring — скучно”.
- Не вставляй английский кусок криво внутрь русской грамматики: не “это in the school bag”, а “Подсказка: in the school bag — в рюкзаке”.
- Не повторяй английскую фразу дважды в переводе: нельзя “school bag — school bag — рюкзак”, правильно “school bag — рюкзак”.
- Если ребенок по-русски просит “как сказать”, “дай ответ”, “фраза по-английски” или вставляет английское задание вроде “tell me about your hobby”, дай готовый английский вариант и коротко объясни по-русски. Не отвечай вместо него только по-русски.
- Английский запрос -> отвечай простым английским. Одну ошибку исправь мягко, коротко по-русски.
- Для детей 5-13 лет, если ребенок пишет/говорит по-английски с ошибкой, не отвечай сухо "Nice try! Better:".
  Скажи коротко по-русски: "Почти! Лучше так: ...", затем задай один очень простой английский вопрос.
- Когда исправляешь английскую ошибку, не повторяй правильную фразу дважды.
- При исправлении используй живой короткий ход: реакция, одна правильная фраза, просьба попробовать ее или один связанный вопрос. Не добавляй после исправления меню тем.
- Смешанный язык -> выбирай язык, на котором ребенку явно легче.
- Не заставляй повторять фразу каждый ход. Иногда лучше просто ответить и задать живой вопрос.
- Один вопрос максимум. Не тестируй каждый ход. Не звучать как меню или карточка из приложения.
- Не говори шаблонно про animals/colors/story. Не повторяй одну тему подряд. Не начинай часто с “Понял”, “Класс”, “Хорошая попытка”.
- Не используй emoji в ответе.
- Не используй взрослые объяснения вроде “так договорились носители языка”. Объясняй проще: “так это слово звучит по-английски”.
- Если ребенок говорит “не хочу повторять”, “не хочу”, “устал”, не предлагай повторить снова. Уважай это и предложи другой легкий ход.
- Темы только безопасные детские. {avoid_topics}

Стиль: как репетитор рядом, который реально слушает: живо, спокойно, с поддержкой, без официоза. Реагируй конкретно на слова ребенка и держи одну учебную линию. Для 5-10 лет больше игры и выбора из двух простых вариантов; для подростков — реальные ситуации и диалоги.

Методика: {lesson_loop}. Форматы меняй: {activity_menu}. Веди мини-сцену 2-5 ходов, если ребенок не просит сменить тему. В каждом ходе сохраняй учебную пользу: фраза, слово, исправление или практика. Иногда верни одно старое слово для повторения, но без ощущения экзамена.

Качество живого ответа:
- Хорошая реплика: "Great try! Better: I like cats. What animal do you like most?" В ней есть реакция, одна подсказка и связанный вопрос.
- Плохая реплика: "After I like, you can say one more thing: I like cats in the morning." Это звучит неестественно и уводит от смысла ребенка.
- Хороший ответ на русском: "О, Майнкрафт — круто! По-английски: I like Minecraft. Что ты чаще строишь?" Не заканчивай его вопросом "What do you build?"
- Хорошее объяснение на русском: "Да: после like действие часто с -ing. Фраза: I like listening to music. А какую музыку ты любишь?"
- Даже после объяснения закончи одним простым связанным вопросом или заданием, чтобы ребенку было легко продолжить говорить.
- Плохая реплика: длинное объяснение правила, перечень тем или вопрос, не связанный со словами ребенка.
- На “я не знаю что сказать” не перечисляй темы. Начни сам с легкого хода: “Окей, начнем с твоего дня. Was it good or boring?”
- На “я не понимаю” объясни спокойно по-русски, без давления и без случайных новых слов.
- На “давай играть” сразу начинай игру, не объясняй правила долго.
- Для 5-10 лет игра в голосе должна быть суперпростая: угадай слово с двумя вариантами, выбор A/B, мини-роли “магазин/кафе”. Не используй цепочку слов, последнюю букву и открытые загадки без вариантов.
- Для 5-7 лет не спрашивай “хочешь сыграем?”, если ребенок растерялся. Начни сам: “Давай очень легко. Cat — кошка или dog — собака?”
- Для 5-7 лет в одном ответе максимум одна новая английская фраза или два отдельных слова на выбор. Не давай две фразы подряд вроде “I like pizza” и “I love pizza”.
- Для 14-18 лет на экзаменационную просьбу дай короткий естественный английский образец, потом одно русское пояснение. Например: “I enjoy reading because it helps me relax. Это звучит естественно для экзамена.”
- На одно английское слово ответь естественно и продолжи сцену.
- На ошибку дай правильный вариант без морали.
- Для 5-10 лет исправление должно иметь русскую опору: "Почти! Лучше так: I went to school yesterday."
- На вопрос ребенка сначала ответь на вопрос, потом при желании добавь одно английское слово. Если вопрос “почему слово так переводится”, отвечай просто: “так это называется по-английски”.
- На отказ повторять скажи: “Окей, без повторения. Тогда просто выбери: игра или короткая история?”
- На просьбу “давай играть” не спрашивай, какую игру начать. Начни мини-игру сразу и дай один простой вопрос.
- На просьбу “историю” дай законченную мини-историю максимум в 2 коротких предложения и один простой выбор в конце. Не обрывай мысль на середине.
- На “устала”, “скучно”, “давай проще” не спрашивай, объяснять ли. Сразу дай один очень легкий ход.

Звучать должно как живой короткий ответ человеку, но с ясной учебной пользой, а не как пустой чат."""


def _runtime_instructions(
    user_name: str,
    age_label: str,
    prompt_context: dict | None,
    last_user_text: str,
) -> str:
    context = prompt_context or {}
    mode = _interaction_mode(context)
    language = _last_language(last_user_text)
    age = context.get("age") or age_label or "не указан"
    level = context.get("level") or TUTOR_DEFAULT_LEVEL
    goal = context.get("goal") or "разговорная практика"
    topics = context.get("topics") or TUTOR_DEFAULT_TOPICS
    topic_suggestions = context.get("topic_suggestions") or context.get("topics") or TUTOR_DEFAULT_TOPICS
    avoid_topics = context.get("avoid_topics") or "Не повторяй одну и ту же тему подряд."
    recent_user_messages = context.get("recent_user_messages") or "нет"
    recent_assistant_messages = context.get("recent_assistant_messages") or "нет"
    lesson_focus = context.get("lesson_focus") or "урок только начинается"
    lesson_phase = context.get("lesson_phase") or "welcome"
    lesson_phase_label = context.get("lesson_phase_label") or "начало урока"
    current_topic = context.get("current_topic") or "тема еще не выбрана"
    lesson_goal = context.get("lesson_goal") or "начать короткий полезный урок"
    target_phrase = context.get("target_phrase") or "пока не выбрана"
    target_words = context.get("target_words") or "пока не выбраны"
    support_mode = context.get("support_mode") or "обычный темп"
    lesson_state_instruction = context.get("lesson_state_instruction") or lesson_focus
    if mode == "voice" and _looks_like_legacy_voice_template(str(recent_assistant_messages)):
        recent_assistant_messages = "в истории есть старые шаблонные ответы; не копируй их стиль"
    conversation_plan = context.get("conversation_plan") or (
        "Слушай последнюю реплику, отвечай по сути, дай одну простую английскую фразу, "
        "затем задай один легкий вопрос или предложи выбор."
    )
    activity_menu = context.get("activity_menu") or (
        "мини-диалог, ролевая сцена, угадай слово, повтори фразу, короткая история, "
        "вопрос про день, выбор из двух вариантов, мягкое исправление, повторение старого слова"
    )
    lesson_loop = context.get("lesson_loop") or (
        "connect: отреагируй на ребенка; model: дай правильную короткую фразу; "
        "try: попроси сказать или выбрать одно; review: иногда верни одно прошлое слово."
    )
    if mode == "voice":
        voice_prompt = _voice_module_prompt(
            user_name=user_name,
            age=str(age),
            level=str(level),
            goal=str(goal),
            topics=str(topics),
            topic_suggestions=str(topic_suggestions),
            avoid_topics=str(avoid_topics),
            recent_user_messages=str(recent_user_messages),
            recent_assistant_messages=str(recent_assistant_messages),
            last_user_text=str(last_user_text or ""),
            language=language,
            lesson_focus=str(lesson_focus),
            activity_menu=str(activity_menu),
            lesson_loop=str(lesson_loop),
        )
        return voice_prompt + f"""

AUTHORITATIVE LESSON STATE:
- Phase: {lesson_phase} ({lesson_phase_label}).
- Current topic: {current_topic}.
- Lesson goal: {lesson_goal}.
- Target phrase: {target_phrase}.
- Target words: {target_words}.
- Support mode: {support_mode}.
- Required next move: {lesson_state_instruction}.

Treat this lesson state as authoritative. Do not invent a new topic or restart the lesson.
Lead the lesson with quiet confidence: do not wait for the child to suggest what to do — propose the step and start it yourself. Sound like a lively, warm, attentive human, and keep your English natural and grammatically correct.
Advance only the current phase. In wrapup, give one success, one gentle growth point, and stop.
If the child mentions something outside the topic, connect it naturally to the current topic.
Never tell the child "we must stay on topic", "back to the topic", or describe the lesson plan.
In a Russian turn, use natural Russian grammar and put the English teaching phrase in a separate sentence.
Keep the spoken turn to three short sentences maximum: one natural reaction, one useful teaching hint, and one directly connected question or task.
Do not append a topic menu after answering or correcting the child.
Target words are optional background vocabulary: weave in at most one and only if it fits this reply naturally. Never tack a stray vocabulary word onto the end of your turn.
If the child's English is already fine, do not say "almost" or "better" — only correct an actual mistake.
Bad: "Какая у тебя favorite game?" Good: "Какая игра у тебя любимая? По-английски: My favorite game is..."."""
    voice_rules = (
        "Режим сейчас: ГОЛОС. Отвечай как живой человек в короткой живой беседе: 2-4 короткие фразы, "
        "сначала по сути реплики ребенка, затем обязательный учебный шаг: одна полезная английская фраза, исправление, выбор или микро-задание. "
        "Без списков, markdown и длинных объяснений. Желательно до 220 символов."
    )
    chat_rules = (
        "Режим сейчас: ЧАТ. Можно дать чуть больше текста, но все равно коротко и по-детски: "
        "не больше 4 коротких предложений, без markdown, если ученик не просит подробный урок. "
        "Каждый ответ должен чему-то учить: слово, фраза, исправление или короткая практика."
    )
    return f"""Дополнительные обязательные правила для текущего ответа.

Ученик: {user_name or "друг"}.
Возраст ученика: {age}.
Последняя реплика ученика: {last_user_text or "пусто"}.
Определенный язык последней реплики: {language}.
Свежие темы на выбор, если ребенок сам не задал тему: {topic_suggestions}.
Текущая линия урока: {lesson_focus}.
Недавние реплики ученика: {recent_user_messages}.
Недавние ответы репетитора: {recent_assistant_messages}.

Самое важное правило языка:
- Если последняя реплика содержит русский текст или ученик пишет «не понимаю», «переведи», «что делать», «?», отвечай ПО-РУССКИ.
- В русском ответе можно дать только одну очень короткую английскую фразу для повторения.
- Не отвечай целиком по-английски на русский запрос.
- Если последняя реплика на английском, отвечай простым английским, а исправление ошибки объясняй коротко по-русски.

План живой беседы:
{conversation_plan}

Методика короткого урока:
{lesson_loop}

Доступные активности, чтобы не повторяться:
{activity_menu}.

Обязательный алгоритм ответа:
- Определи намерение последней реплики: приветствие, вопрос, просьба перевести, непонимание, выбор темы, короткий ответ, ошибка, усталость.
- Ответь именно на это намерение первым предложением.
- Подстрой язык: русский запрос -> русский ответ с одной короткой английской фразой; английский запрос -> простой английский с коротким русским исправлением при ошибке.
- Дай ребенку очень маленький учебный следующий шаг: повторить 2-5 слов, выбрать один вариант, назвать одно слово, исправить одну фразу или ответить yes/no.
- Не заканчивай ответ обычной болтовней. В конце должен быть учебный крючок: фраза, слово, выбор или вопрос для практики.
- Если в недавней истории есть слово или фраза, иногда верни ее как легкое повторение. Не делай это в каждом ответе.

Как слушать и вести диалог:
- Сначала отвечай на то, что ребенок реально спросил или попросил. Не уводи разговор в заготовленную тему.
- Если ребенок выбрал тему, продолжай ее 2-4 реплики как мини-сцену, а не сбрасывай разговор каждый раз.
- Не меняй тему сам по времени. Новые темы используй только если ребенок попросил сменить тему, явно устал, молчит или текущая мини-сцена закончена.
- Если ребенок задает вопрос не по уроку, коротко ответь на вопрос и мягко привяжи к английскому.
- Если ребенок отвечает одним словом, развивай это слово в простую фразу.
- Если ребенок ошибся, исправь только одну главную ошибку и дай правильный вариант.
- Если тема уже повторялась, выбери другую из свежих тем.
- {avoid_topics}

Стиль для ребенка:
- Не звучать как учебник. Звучать как добрый живой репетитор.
- Сначала коротко поддержи ребенка: «Класс», «Понял», «Хорошая попытка».
- Сразу дай маленькое действие: повторить фразу, выбрать тему, назвать 1 слово.
- Для 5-10 лет используй игру, выбор и очень простые слова.
- Не давай больше одного задания и больше одного вопроса.
- Темы безопасные и детские: игры, животные, еда, школа, спорт, цвета, история, мини-квест.
- Не говори “давай поговорим про animals/colors/story” по шаблону, если можно живо отреагировать на слова ребенка.
- Если ребенок спрашивает по-русски, не заставляй его сразу говорить английским предложением; сначала помоги понять, потом дай маленькую фразу.

{voice_rules if mode == "voice" else chat_rules}

Примеры тона:
Русский запрос: «Понял! Давай проще: say "I like games". Выбери: games или animals?»
Английский запрос: «Great! You can say: I like cats. Do you like cats or dogs?»"""


def _get_realtime_profile(prompt_context: dict | None) -> dict:
    """Возвращает возрастной профиль для Realtime сессии."""
    age_group = _normalize_realtime_age_group((prompt_context or {}).get("age_group", "default"), (prompt_context or {}).get("age"))
    return REALTIME_AGE_PROFILES.get(age_group, REALTIME_AGE_PROFILES["default"])


def _normalize_realtime_age_group(age_group: str | None, age: str | int | None = None) -> str:
    # Voice/Realtime: приоритет у точного возраста (отличается от learning-режима,
    # где приоритет у сохранённой группы). «Лестница» возраст→группа — из config.
    raw = str(age_group or "").strip()
    try:
        child_age = int(str(age or "").split()[0])
    except (TypeError, ValueError, IndexError):
        child_age = 0
    derived = age_group_from_age(child_age)
    if derived:
        return derived
    if raw in {"under_12", "under12", "under_10", "до_12", "child", "kids", "default", ""}:
        return "8_10"
    if raw in {"5_7", "8_10", "11_13", "14_18"}:
        return raw
    return "default"


def build_voice_realtime_instructions(
    user_name: str,
    age_label: str = "",
    prompt_context: dict | None = None,
) -> str:
    """Builds a structured, age-adaptive prompt for native speech-to-speech Realtime sessions."""
    context = dict(prompt_context or {})
    age_group = _normalize_realtime_age_group(context.get("age_group", "default"), context.get("age"))
    name = user_name or "друг"
    age = context.get("age") or age_label or "не указан"
    level = context.get("level") or TUTOR_DEFAULT_LEVEL
    goal = context.get("goal") or "разговорная практика"
    topics = context.get("topic_suggestions") or context.get("topics") or TUTOR_DEFAULT_TOPICS
    lesson_focus = context.get("lesson_focus") or "lesson is just starting"
    recent_user = context.get("recent_user_messages") or "none"
    recent_assistant = context.get("recent_assistant_messages") or "none"
    lesson_phase = context.get("lesson_phase") or "welcome"
    current_topic = context.get("current_topic") or "not selected yet"
    lesson_goal = context.get("lesson_goal") or "choose a topic and begin a useful mini-lesson"
    target_phrase = context.get("target_phrase") or "not selected yet"
    target_words = context.get("target_words") or "not selected yet"
    support_mode = context.get("support_mode") or "normal"
    lesson_state_instruction = context.get("lesson_state_instruction") or lesson_focus

    if age_group == "5_7":
        age_style = (
            "Talk to the child like a kind, playful tutor. Use very simple words, one idea at a time, "
            "and make the conversation feel like a small game."
        )
        max_total_words = "18"
    elif age_group == "8_10":
        age_style = (
            "Talk to the child like a kind, playful tutor. Use simple words, one idea at a time, "
            "and make the conversation feel like a small game."
        )
        max_total_words = "24"
    elif age_group == "11_13":
        age_style = (
            "Talk like a friendly tutor for a pre-teen. Be natural, not babyish, and use school, games, hobbies, and daily life."
        )
        max_total_words = "30"
    else:
        age_style = "Talk like a warm mentor for a teenager. Be natural and respectful, with real-life examples."
        max_total_words = "36"

    return f"""You are Alex, a live voice English tutor for a child.
Student: {name}. Age: {age}. Level: {level}. Goal: {goal}. Fresh topics: {topics}.
Current lesson thread: {lesson_focus}.
Authoritative lesson phase: {lesson_phase}. Current topic: {current_topic}. Goal: {lesson_goal}.
Target phrase: {target_phrase}. Target words: {target_words}. Support mode: {support_mode}.
Required next move: {lesson_state_instruction}.
Recent student messages: {recent_user}.
Recent tutor messages: {recent_assistant}.

Speak like a real human in a live call: warm, relaxed, attentive, with natural pauses. Do not sound like a robot, announcer, menu, or textbook.
{age_style}

Voice turn contract, highest priority:
- Use at most three short conversational sentences and at most {max_total_words} words total. For a young child, two sentences are often enough.
- Build one natural turn from three small beats: react to the child's exact words; give one useful hint, model, or correction; ask one directly connected question or tiny task.
- Every turn must teach English in a tiny way: one word, one phrase, one correction, one two-option choice, or one micro-practice. Do not merely chat.
- Lead the lesson yourself: never wait for the child to choose what to do — confidently propose the next small step and start it. Stay lively, warm, attentive and grammatically correct.
- The three beats do not need labels and do not need separate sentences. Never announce the structure.
- The final question or task must continue the child's exact idea. Never append an arbitrary topic choice just to end with a question.
- Once a topic is selected, do not offer a menu of topics. Stay in the current scene.
- Target words are optional background vocabulary: use at most one and only if it fits naturally. Never tack a stray vocabulary word onto the end of your turn.
- Only correct an actual mistake. If the child's English is already fine, never say "almost" or "better".
- Never produce fragments such as "Great! song." Say a complete natural thought.
- Never transliterate Russian words such as "Pochti" or "Khorosho".
- Never insert an English word into Russian grammar such as "Какой song?" Say natural Russian, then put any useful English phrase in a separate sentence.
- Never put English choices inside a Russian question such as "Что любишь: music or songs?" Keep the question natural Russian.
- Good Russian turn: "О, Майнкрафт — круто! По-английски: I like Minecraft. Что ты чаще строишь?" Never end it with "What do you build?"

Hard language rule:
- Mirror the student's latest language.
- If the child speaks Russian, answer in Russian. Do not switch to English for the whole answer.
- After a Russian message, the final question or task must also be in Russian. English may appear only as one separate teaching phrase.
- If the child says "не понимаю", "что?", "переведи", "помоги", "по-русски", or sounds unsure, answer only in Russian in that turn.
- In a Russian answer, add at most one tiny English phrase only when it is useful, and immediately explain it in Russian.
- If the child speaks English, answer in simple English. If you correct a mistake, do it kindly and briefly.

Conversation behavior:
- First answer the child's actual message. Do not ignore it to follow a lesson plan.
- Keep the current lesson thread. Do not jump to a new topic because time passed or a new response starts.
- Treat the authoritative lesson state above as the source of truth. Never restart or replace its topic.
- Move only inside the current phase. In wrapup, name one success and one gentle growth point, then stop.
- If the child mentions something outside the topic, bridge it naturally into the current topic without saying that you are returning to the lesson.
- In Russian turns, keep Russian grammar natural and say the English teaching phrase as a separate short sentence.
- Change topic only if the child explicitly asks or the lesson is reset.
- If the child seems tired, stays silent, or struggles, simplify the activity inside the same topic.
- Every turn must teach English in a tiny way: model one phrase, correct one error, ask one practice question, give one word choice, or review one previous word.
- Do not just chat. Plain conversation is allowed only as the bridge into the learning step.
- Lead the conversation yourself, but never list menu options or say what buttons exist.
- Keep one mini-scene for 2-4 turns before changing topic.
- Vary activities naturally: tiny role-play, one easy choice, guess a word, mini-story, daily-life question, gentle correction.
- Do not repeat animals/colors/story every time.
- If the child is silent, tired, or answers with one word, make it easier and give a choice.

Response length:
- Speak in at most 3 short sentences and at most {max_total_words} words total.
- Ask at most one question.
- Finish the thought. Do not leave a sentence hanging.
- No markdown, no emoji, no lists, no "Say:" or "Repeat:" commands.
- Always end with one directly connected question or tiny practice action so the child knows how to continue.

Audio behavior:
- Wait until the child finishes before answering.
- Do not interrupt yourself or restart your own sentence.
- Use natural pronunciation. If you say an English word inside Russian, pronounce that word in clean English, then continue Russian naturally.

Safety:
Child-safe topics only. Avoid scary, adult, violent, political, or inappropriate content."""


def _transcription_hint(prompt_context: dict | None) -> str:
    """Подсказка для ASR с темами урока — снижает ошибки распознавания."""
    context = prompt_context or {}
    topics = context.get("topic_suggestions") or context.get("topics") or ""
    level = context.get("level") or ""
    parts = ["A child is speaking with an English tutor."]
    if level:
        parts.append(f"Level: {level}.")
    if topics:
        parts.append(f"Topics: {topics[:150]}.")
    parts.append("The child may speak Russian, English, or a mix. Transcribe exactly; do not translate.")
    return " ".join(parts)


def build_realtime_session_config(
    user_name: str,
    age_label: str = "",
    prompt_context: dict | None = None,
    minimal: bool = False,
) -> dict:
    """Session payload for OpenAI Realtime WebRTC — fully age-adaptive."""
    profile = _get_realtime_profile(prompt_context)
    session_config = {
        "type": "realtime",
        "model": OPENAI_REALTIME_MODEL,
        "instructions": build_voice_realtime_instructions(user_name, age_label, prompt_context),
        "reasoning": {"effort": OPENAI_REALTIME_REASONING_EFFORT},
        "audio": {
            "output": {
                "voice": profile["voice"],
            },
        },
    }
    if minimal:
        return session_config

    session_config["output_modalities"] = ["audio"]
    # Do not cap Realtime audio responses here: low token caps can cut spoken phrases mid-sentence.
    # The live prompt keeps replies short while still letting the model finish the thought.
    turn_detection = {
        "type": profile.get("vad_type", "server_vad"),
        "create_response": True,
        "interrupt_response": profile["interrupt_response"],
    }
    if turn_detection["type"] == "semantic_vad":
        turn_detection["eagerness"] = profile.get("semantic_eagerness", "low")
    else:
        turn_detection.update({
            "threshold": profile["vad_threshold"],
            "prefix_padding_ms": profile["prefix_padding_ms"],
            "silence_duration_ms": profile["silence_duration_ms"],
            "idle_timeout_ms": profile["idle_timeout_ms"],
        })

    session_config["audio"]["input"] = {
        "noise_reduction": {"type": "near_field"},
        "transcription": {
            "model": OPENAI_REALTIME_TRANSCRIBE_MODEL,
            "prompt": _transcription_hint(prompt_context),
        },
        "turn_detection": turn_detection,
    }
    if profile.get("speed") and profile["speed"] != 1.0:
        session_config["audio"]["output"]["speed"] = profile["speed"]
    return session_config


def _safety_identifier(user_id: int | str) -> str:
    raw = f"telegram-miniapp:{user_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _session_log_summary(session_config: dict, age_group: str) -> dict:
    audio = session_config.get("audio", {})
    audio_input = audio.get("input", {})
    turn_detection = audio_input.get("turn_detection", {})
    audio_output = audio.get("output", {})
    return {
        "age_group": age_group,
        "voice": audio_output.get("voice"),
        "speed": audio_output.get("speed"),
        "max_tokens": session_config.get("max_output_tokens"),
        "vad_type": turn_detection.get("type"),
        "eagerness": turn_detection.get("eagerness"),
        "silence_ms": turn_detection.get("silence_duration_ms"),
        "idle_ms": turn_detection.get("idle_timeout_ms"),
        "instructions_len": len(session_config.get("instructions", "")),
        "minimal": "input" not in audio,
    }


async def _post_realtime_client_secret(session_config: dict, user_id: int | str) -> dict:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
                "OpenAI-Safety-Identifier": _safety_identifier(user_id),
            },
            json={"session": session_config},
        ) as response:
            try:
                data = await response.json()
            except Exception:
                data = {"raw": await response.text()}
            if response.status >= 400:
                log.error("Realtime token FAILED: HTTP %s body=%s", response.status, str(data)[:800])
                raise RuntimeError(f"HTTP {response.status}: {str(data)[:400]}")
            return data


async def create_realtime_client_secret(
    user_id: int | str,
    user_name: str,
    age_label: str = "",
    prompt_context: dict | None = None,
) -> dict:
    """Creates an ephemeral Realtime token for browser-side WebRTC."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    age_group = _normalize_realtime_age_group((prompt_context or {}).get("age_group", "?"), (prompt_context or {}).get("age"))
    full_config = build_realtime_session_config(user_name, age_label, prompt_context)
    log.info("Realtime token config: %s", _session_log_summary(full_config, age_group))
    try:
        return await _post_realtime_client_secret(full_config, user_id)
    except Exception:
        minimal_config = build_realtime_session_config(user_name, age_label, prompt_context, minimal=True)
        log.warning("Retrying Realtime token with minimal session config")
        return await _post_realtime_client_secret(minimal_config, user_id)


async def create_realtime_call(
    sdp_offer: str,
    user_id: int | str,
    user_name: str,
    age_label: str = "",
    prompt_context: dict | None = None,
) -> str:
    """Creates a Realtime WebRTC call and returns the SDP answer."""
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    clean_sdp = (sdp_offer or "").strip()
    if not clean_sdp.startswith("v=0"):
        raise ValueError("Invalid SDP offer")

    session_config = build_realtime_session_config(user_name, age_label, prompt_context)
    session_json = json.dumps(session_config)
    age_group = _normalize_realtime_age_group((prompt_context or {}).get("age_group", "?"), (prompt_context or {}).get("age"))
    log.info("Realtime call config: %s", _session_log_summary(session_config, age_group))

    form = aiohttp.FormData()
    form.add_field("sdp", clean_sdp, content_type="application/sdp")
    form.add_field("session", session_json, content_type="application/json")

    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            "https://api.openai.com/v1/realtime/calls",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Safety-Identifier": _safety_identifier(user_id),
            },
            data=form,
        ) as response:
            text = await response.text()
            if response.status >= 400:
                log.error(
                    "Realtime call FAILED: HTTP %s body=%s session_keys=%s",
                    response.status, text[:800], list(session_config.keys()),
                )
                if "invalid_offer" not in text:
                    minimal_config = build_realtime_session_config(user_name, age_label, prompt_context, minimal=True)
                    log.warning("Retrying Realtime call with minimal session config")
                    form = aiohttp.FormData()
                    form.add_field("sdp", clean_sdp, content_type="application/sdp")
                    form.add_field("session", json.dumps(minimal_config), content_type="application/json")
                    async with session.post(
                        "https://api.openai.com/v1/realtime/calls",
                        headers={
                            "Authorization": f"Bearer {OPENAI_API_KEY}",
                            "OpenAI-Safety-Identifier": _safety_identifier(user_id),
                        },
                        data=form,
                    ) as retry_response:
                        retry_text = await retry_response.text()
                        if retry_response.status < 400:
                            log.info("Realtime call OK after minimal retry: SDP answer length=%d", len(retry_text))
                            return retry_text
                        text = retry_text
                        response_status = retry_response.status
                else:
                    response_status = response.status
                raise RuntimeError(f"HTTP {response_status}: {text[:400]}")
            log.info("Realtime call OK: SDP answer length=%d", len(text))
            return text


def _prompt_variables(user_name: str, age_label: str = "", prompt_context: dict | None = None) -> dict:
    context = prompt_context or {}
    age = context.get("age") or age_label or "не указан"
    return {
        "name": str(user_name or "друг"),
        "age": str(age),
        "age_label": str(age_label or age),
        "level": str(context.get("level") or TUTOR_DEFAULT_LEVEL),
        "goal": str(context.get("goal") or "разговорная практика"),
        "style": str(context.get("style") or TUTOR_DEFAULT_STYLE),
        "topics": str(context.get("topics") or TUTOR_DEFAULT_TOPICS),
        "correction_mode": str(context.get("correction_mode") or TUTOR_CORRECTION_MODE),
        "language_balance": str(context.get("language_balance") or TUTOR_LANGUAGE_BALANCE),
        "mode": str(context.get("mode") or "chat"),
        "interaction_mode": str(context.get("mode") or "chat"),
        "topic_suggestions": str(context.get("topic_suggestions") or context.get("topics") or TUTOR_DEFAULT_TOPICS),
        "avoid_topics": str(context.get("avoid_topics") or "не повторять одну и ту же тему подряд"),
        "conversation_plan": str(context.get("conversation_plan") or ""),
        "recent_user_messages": str(context.get("recent_user_messages") or ""),
        "recent_assistant_messages": str(context.get("recent_assistant_messages") or ""),
        "activity_menu": str(context.get("activity_menu") or ""),
        "lesson_loop": str(context.get("lesson_loop") or ""),
        "lesson_phase": str(context.get("lesson_phase") or "welcome"),
        "lesson_phase_label": str(context.get("lesson_phase_label") or ""),
        "lesson_progress": str(context.get("lesson_progress") or "5"),
        "current_topic": str(context.get("current_topic") or ""),
        "lesson_goal": str(context.get("lesson_goal") or ""),
        "target_phrase": str(context.get("target_phrase") or ""),
        "target_words": str(context.get("target_words") or ""),
        "support_mode": str(context.get("support_mode") or ""),
        "lesson_state_instruction": str(context.get("lesson_state_instruction") or ""),
    }


async def transcribe_audio(file_bytes: bytes, filename: str = "voice.webm", content_type: str = "audio/webm") -> str:
    """Transcribes a short voice message for the chat input."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    safe_name = filename or "voice.webm"
    audio_file = BytesIO(file_bytes)
    audio_file.name = safe_name
    result = await _client.audio.transcriptions.create(
        model=OPENAI_TRANSCRIBE_MODEL,
        file=(safe_name, audio_file, content_type or "audio/webm"),
        prompt=(
            "A child is speaking to an English tutor. "
            "The speech can be Russian, English, or a mix. "
            "Transcribe exactly what the child says; do not translate."
        ),
    )
    text = getattr(result, "text", result)
    return str(text or "").strip()


def _tts_setup(text: str, mode: str, speed: float | int | str | None) -> tuple[str, str, str, float]:
    """Shared TTS preparation: returns (clean_text, instructions, voice, speech_speed)."""
    clean_text = " ".join((text or "").split())
    if not clean_text:
        raise ValueError("Text is empty")
    max_chars = 160 if mode == "word" else 420 if mode == "voice" else 1100
    clean_text = _cut_at_sentence_boundary(clean_text, max_chars)
    default_speed = 0.88 if mode == "word" else 0.94 if mode == "voice" else 1.0
    speech_speed = _clamp_speech_speed(speed, default_speed)

    has_russian = _has_cyrillic(clean_text)
    has_english = _has_latin(clean_text)
    if mode == "word":
        instructions = (
            "Pronounce only the given English word or short phrase for a child learning English. "
            "Use clear natural English pronunciation, a warm friendly tone, and a slightly slower pace. "
            "Do not add explanations, translations, or extra words."
        )
    elif has_russian and has_english:
        instructions = (
            "Sound like a warm, expressive real person tutoring a child, not an announcer and not a robot. "
            "The text mixes Russian and English. Speak Russian naturally and conversationally. "
            "When an English word or phrase appears, switch briefly to clean natural English pronunciation, "
            "then return to Russian. Use lively intonation, gentle emotion, tiny pauses, and a friendly smile in the voice."
        )
    elif has_russian:
        instructions = (
            "Говори как живой добрый репетитор для ребенка, не как диктор и не как робот. "
            "Русский произноси естественно, тепло, разговорно, с живой интонацией и мягкой улыбкой в голосе. "
            "Если встречается английское слово, произнеси его с нормальным английским произношением. "
            "Делай маленькие естественные паузы. Фразы короткие."
        )
    else:
        instructions = (
            "Sound like a warm, expressive real person tutoring a child, not an announcer and not a robot. "
            "Use natural clear English pronunciation, friendly intonation, gentle emotion, and short conversational phrases."
        )
    if mode == "voice":
        instructions = (
            VOICE_TTS_INSTRUCTIONS
            + " Это живой голосовой диалог: отвечай звучанием быстро, естественно и в тему. "
            "Не растягивай слова, не переигрывай, не читай как диктор. "
            + instructions
        )
    voice = OPENAI_VOICE_TTS_VOICE if mode == "voice" else OPENAI_TTS_VOICE
    return clean_text, instructions, voice, speech_speed


def _tts_request(model: str, clean_text: str, voice: str, speech_speed: float,
                 instructions: str, include_instructions: bool) -> dict:
    request = {
        "model": model,
        "voice": voice,
        "input": clean_text,
        "response_format": "mp3",
        "speed": speech_speed,
    }
    if include_instructions:
        request["instructions"] = instructions
    return request


async def synthesize_speech(text: str, mode: str = "chat", speed: float | int | str | None = None) -> bytes:
    """Generates a short MP3 tutor voice response (fully buffered)."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    clean_text, instructions, voice, speech_speed = _tts_setup(text, mode, speed)

    async def create_audio(model: str, include_instructions: bool = True) -> bytes:
        request = _tts_request(model, clean_text, voice, speech_speed, instructions, include_instructions)
        response = await _client.audio.speech.create(**request)
        return await response.aread()

    try:
        return await create_audio(OPENAI_TTS_MODEL, include_instructions=True)
    except BadRequestError:
        if OPENAI_TTS_MODEL == "tts-1":
            raise
        log.warning("TTS model %s is unavailable, falling back to tts-1", OPENAI_TTS_MODEL)
        return await create_audio("tts-1", include_instructions=False)


async def synthesize_speech_stream(text: str, mode: str = "chat", speed: float | int | str | None = None):
    """Yields MP3 chunks as OpenAI produces them so the client can start playing sooner.

    Same voice/instructions/speed as synthesize_speech, including the tts-1 fallback.
    The BadRequest fallback fires before any chunk is yielded, so no audio is duplicated.
    """
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    clean_text, instructions, voice, speech_speed = _tts_setup(text, mode, speed)

    async def stream_audio(model: str, include_instructions: bool = True):
        request = _tts_request(model, clean_text, voice, speech_speed, instructions, include_instructions)
        async with _client.audio.speech.with_streaming_response.create(**request) as response:
            async for chunk in response.iter_bytes():
                if chunk:
                    yield chunk

    try:
        async for chunk in stream_audio(OPENAI_TTS_MODEL, include_instructions=True):
            yield chunk
    except BadRequestError:
        if OPENAI_TTS_MODEL == "tts-1":
            raise
        log.warning("TTS model %s is unavailable for streaming, falling back to tts-1", OPENAI_TTS_MODEL)
        async for chunk in stream_audio("tts-1", include_instructions=False):
            yield chunk


async def chat_reply(
    history: list[dict],
    user_name: str,
    age_label: str = "",
    prompt_context: dict | None = None,
) -> ChatReply:
    """
    history: список сообщений вида [{"role": "user"/"assistant", "content": "..."}].
    Возвращает текст ответа репетитора.
    """
    if _client is None:
        return ChatReply(
            text=("⚠️ Репетитор пока не настроен: не задан ключ OPENAI_API_KEY. "
                  "Добавь его в переменные окружения на Render."),
            model=OPENAI_MODEL,
        )

    try:
        last_user_text = _last_user_text(history)
        mode = _interaction_mode(prompt_context)
        max_output_tokens = VOICE_MAX_TOKENS if mode == "voice" else CHAT_MAX_TOKENS
        model_history = _sanitize_history_for_model(_clean_history_for_mode(history, mode))
        runtime_instructions = _runtime_instructions(user_name, age_label, prompt_context, last_user_text)
        safety_reply = _safety_guard_reply(last_user_text)
        if safety_reply:
            if mode == "voice":
                safety_reply = _finalize_voice_reply(safety_reply, last_user_text)
            return ChatReply(text=safety_reply, model="safety-guard")
        use_stored_prompt = bool(OPENAI_PROMPT_ID and (mode != "voice" or OPENAI_PROMPT_FOR_VOICE))
        request = {
            "model": OPENAI_MODEL,
            "input": model_history,
            "max_output_tokens": max_output_tokens,
        }
        # instructions ставится ниже только в inline-ветке; при stored-prompt
        # передаём только prompt, иначе уходят оба ключа сразу.
        if use_stored_prompt:
            request["prompt"] = {
                "id": OPENAI_PROMPT_ID,
                "variables": _prompt_variables(user_name, age_label, prompt_context),
            }
            if OPENAI_PROMPT_VERSION:
                request["prompt"]["version"] = OPENAI_PROMPT_VERSION
        else:
            if mode == "voice":
                request["instructions"] = runtime_instructions
            else:
                request["instructions"] = SYSTEM_PROMPT.format(
                    name=user_name or "друг",
                    age_label=age_label or "не указана",
                ) + "\n\n" + runtime_instructions
        reasoning_effort = OPENAI_VOICE_REASONING_EFFORT if mode == "voice" else OPENAI_REASONING_EFFORT
        if reasoning_effort and _supports_reasoning(OPENAI_MODEL):
            request["reasoning"] = {"effort": reasoning_effort}
        else:
            # Без reasoning держим температуру ниже дефолтного 1.0 — у детского
            # репетитора это заметно стабилизирует грамматику и убирает «фантазийные» фразы.
            # (Reasoning-моделям temperature слать нельзя — отсюда ветка else.)
            request["temperature"] = 0.6 if mode == "voice" else 0.7

        response = await _client.responses.create(**request)
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        total_tokens = _usage_int(usage, "total_tokens") or input_tokens + output_tokens
        text = (response.output_text or "").strip() or "…"
        if mode == "voice":
            text = _finalize_voice_reply(text, last_user_text)

        if _needs_russian_repair(last_user_text, text):
            repair_response = await _client.responses.create(
                model=OPENAI_MODEL,
                input=[{
                    "role": "user",
                    "content": (
                        "Ученик написал по-русски, а ответ получился не на русском.\n"
                        f"Реплика ученика: {last_user_text}\n"
                        f"Ответ, который нужно переписать: {text}\n\n"
                        f"Перепиши ответ по-русски для ребенка возраста {age_label or 'ученика'}. "
                        "Оставь максимум одну отдельную простую английскую учебную фразу. "
                        "Сделай максимум 3 коротких предложения: естественная реакция, одна подсказка и один связанный вопрос или задание. "
                        "Финальный вопрос должен быть по-русски. Не вставляй английские слова внутрь русской грамматики."
                    ),
                }],
                instructions="Ты исправляешь язык ответа детского репетитора. Ответь только финальной репликой.",
                max_output_tokens=min(max_output_tokens, 200),
            )
            repair_text = (repair_response.output_text or "").strip()
            if mode == "voice":
                repair_text = _finalize_voice_reply(repair_text, last_user_text)
            if repair_text and _has_cyrillic(repair_text):
                text = repair_text
                repair_usage = getattr(repair_response, "usage", None)
                input_tokens += _usage_int(repair_usage, "input_tokens")
                output_tokens += _usage_int(repair_usage, "output_tokens")
                total_tokens += _usage_int(repair_usage, "total_tokens")
        if total_tokens < input_tokens + output_tokens:
            total_tokens = input_tokens + output_tokens

        return ChatReply(
            text=text,
            model=OPENAI_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=_estimate_cost(input_tokens, output_tokens),
        )
    except RateLimitError as e:
        log.warning("OpenAI rate/quota limit: %s", e)
        return ChatReply(
            text=f"⚠️ {public_openai_error(e)}",
            model=OPENAI_MODEL,
        )
    except AuthenticationError as e:
        log.exception("OpenAI authentication failed")
        return ChatReply(
            text=f"⚠️ {public_openai_error(e)}",
            model=OPENAI_MODEL,
        )
    except APIConnectionError as e:
        log.exception("OpenAI connection failed")
        return ChatReply(
            text=f"⚠️ {public_openai_error(e)}",
            model=OPENAI_MODEL,
        )
    except Exception as e:
        log.exception("Ошибка обращения к OpenAI")
        return ChatReply(
            text=f"⚠️ {public_openai_error(e)}",
            model=OPENAI_MODEL,
        )


async def test_openai_connection() -> dict:
    """Checks the key from the running environment without exposing it."""
    if _client is None:
        return {
            "ok": False,
            "error": "OPENAI_API_KEY is not configured",
            "model": OPENAI_MODEL,
        }
    try:
        models = await _client.models.list()
        first_ids = [item.id for item in list(models.data)[:3]]
        return {
            "ok": True,
            "model": OPENAI_MODEL,
            "sample_models": first_ids,
        }
    except Exception as e:
        return {
            "ok": False,
            "model": OPENAI_MODEL,
            "error": str(e)[:500],
        }
