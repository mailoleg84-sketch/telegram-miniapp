"""Обёртка над OpenAI API: ИИ-репетитор английского."""
from dataclasses import dataclass
from io import BytesIO
import logging

from openai import AsyncOpenAI, BadRequestError, RateLimitError

from config import (
    CHAT_MAX_TOKENS,
    OPENAI_INPUT_COST_PER_1M,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_OUTPUT_COST_PER_1M,
    OPENAI_REASONING_EFFORT,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TRANSCRIBE_MODEL,
)

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
if OPENAI_API_KEY:
    _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    log.info(
        "OpenAI API key configured: length=%s prefix=%s",
        len(OPENAI_API_KEY),
        OPENAI_API_KEY[:7],
    )
else:
    log.warning("OPENAI_API_KEY не задан — режим репетитора работать не будет.")


def openai_config_status() -> dict:
    """Safe diagnostics without exposing the secret."""
    return {
        "configured": bool(OPENAI_API_KEY),
        "length": len(OPENAI_API_KEY),
        "prefix": OPENAI_API_KEY[:8] if OPENAI_API_KEY else "",
        "model": OPENAI_MODEL,
    }


SYSTEM_PROMPT = """Ты — дружелюбный и терпеливый AI-репетитор английского языка для русскоязычного ребенка по имени {name}.

Возрастная группа ученика: {age_label}.

Правила:
- Основной режим: веди живой разговор на английском.
- Отвечай коротко: 2–4 предложения.
- Подстраивай сложность, тон и темы под возраст.
- Для детей 5–10 лет используй очень простые слова, игровые примеры и мягкий тон.
- Для подростков 14–18 лет можно говорить чуть взрослее, но без неподходящих тем.
- Если есть заметная ошибка, мягко исправь и кратко объясни по-русски.
- Режим поддержки на русском включается автоматически, если ученик пишет по-русски, говорит что не понимает, просит перевод, присылает только знак вопроса или явно путается.
- В режиме поддержки отвечай именно на русском языке. Не спрашивай, нужно ли объяснить по-русски.
- В режиме поддержки: сначала просто объясни смысл по-русски, затем дай 1–2 очень простые английские фразы для повторения. После этого мягко верни ученика к английскому.
- Если ученик пишет русскую фразу и хочет сказать её по-английски, дай английский вариант и короткое русское объяснение.
- Иногда задавай простой вопрос, чтобы продолжить разговор.
- Не обсуждай взрослые, опасные или неподходящие для детей темы.

Отвечай обычным текстом, без markdown-разметки и без списков."""


@dataclass(frozen=True)
class ChatReply:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


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


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    input_cost = input_tokens * OPENAI_INPUT_COST_PER_1M / 1_000_000
    output_cost = output_tokens * OPENAI_OUTPUT_COST_PER_1M / 1_000_000
    return round(input_cost + output_cost, 6)


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
        prompt="Child learning English. Speech may be in Russian or English.",
    )
    text = getattr(result, "text", result)
    return str(text or "").strip()


async def synthesize_speech(text: str) -> bytes:
    """Generates a short MP3 tutor voice response."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    clean_text = " ".join((text or "").split())
    if not clean_text:
        raise ValueError("Text is empty")
    if len(clean_text) > 900:
        clean_text = clean_text[:900]

    is_russian = any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in clean_text)
    instructions = (
        "Говори дружелюбно, мягко и понятно для ребенка. Темп спокойный."
        if is_russian else
        "Speak warmly and clearly for a child learning English. Keep a calm, friendly pace."
    )
    async def create_audio(model: str, include_instructions: bool = True) -> bytes:
        request = {
            "model": model,
            "voice": OPENAI_TTS_VOICE,
            "input": clean_text,
            "response_format": "mp3",
            "speed": 0.95,
        }
        if include_instructions:
            request["instructions"] = instructions
        response = await _client.audio.speech.create(**request)
        return await response.aread()

    try:
        return await create_audio(OPENAI_TTS_MODEL, include_instructions=True)
    except BadRequestError:
        if OPENAI_TTS_MODEL == "tts-1":
            raise
        log.warning("TTS model %s is unavailable, falling back to tts-1", OPENAI_TTS_MODEL)
        return await create_audio("tts-1", include_instructions=False)


async def chat_reply(history: list[dict], user_name: str, age_label: str = "") -> ChatReply:
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
        request = {
            "model": OPENAI_MODEL,
            "instructions": SYSTEM_PROMPT.format(
                name=user_name or "друг",
                age_label=age_label or "не указана",
            ),
            "input": history,
            "max_output_tokens": CHAT_MAX_TOKENS,
        }
        if OPENAI_REASONING_EFFORT and _supports_reasoning(OPENAI_MODEL):
            request["reasoning"] = {"effort": OPENAI_REASONING_EFFORT}

        response = await _client.responses.create(**request)
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        total_tokens = _usage_int(usage, "total_tokens") or input_tokens + output_tokens

        return ChatReply(
            text=(response.output_text or "").strip() or "…",
            model=OPENAI_MODEL,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_usd=_estimate_cost(input_tokens, output_tokens),
        )
    except RateLimitError as e:
        log.warning("OpenAI rate/quota limit: %s", e)
        message = str(e)
        if "insufficient_quota" in message:
            text = ("⚠️ У OpenAI закончилась квота или не включена оплата. "
                    "Проверь billing и limits в кабинете OpenAI.")
        else:
            text = "⚠️ OpenAI временно ограничил запросы. Попробуй позже."
        return ChatReply(
            text=text,
            model=OPENAI_MODEL,
        )
    except Exception as e:
        log.exception("Ошибка обращения к OpenAI")
        return ChatReply(
            text=f"⚠️ Не удалось получить ответ от репетитора: {e}",
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
