"""Обёртка над OpenAI API: ИИ-репетитор английского."""
from dataclasses import dataclass
from io import BytesIO
import logging

from openai import APIConnectionError, AuthenticationError, AsyncOpenAI, BadRequestError, RateLimitError

from config import (
    CHAT_MAX_TOKENS,
    OPENAI_INPUT_COST_PER_1M,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_OUTPUT_COST_PER_1M,
    OPENAI_PROMPT_FOR_VOICE,
    OPENAI_PROMPT_ID,
    OPENAI_PROMPT_VERSION,
    OPENAI_REASONING_EFFORT,
    OPENAI_TTS_MODEL,
    OPENAI_TTS_VOICE,
    OPENAI_TRANSCRIBE_MODEL,
    OPENAI_VOICE_TTS_VOICE,
    TUTOR_CORRECTION_MODE,
    TUTOR_DEFAULT_LEVEL,
    TUTOR_DEFAULT_STYLE,
    TUTOR_DEFAULT_TOPICS,
    TUTOR_LANGUAGE_BALANCE,
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
        "tts_model": OPENAI_TTS_MODEL,
        "tts_voice": OPENAI_TTS_VOICE,
        "voice_tts_voice": OPENAI_VOICE_TTS_VOICE,
        "prompt_id_configured": bool(OPENAI_PROMPT_ID),
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_for_voice": OPENAI_PROMPT_FOR_VOICE,
    }


def public_openai_error(error: Exception) -> str:
    """Returns a child-safe error message without leaking secrets or raw provider payloads."""
    if isinstance(error, AuthenticationError):
        return "Репетитор пока не настроен. Родителю нужно обновить ключ OpenAI."
    if isinstance(error, RateLimitError):
        message = str(error)
        if "insufficient_quota" in message:
            return "У OpenAI закончилась квота или не включена оплата. Проверь billing и limits."
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
    "Говори как живой добрый репетитор для ребенка. Тепло, естественно, разговорно, "
    "с мягкой интонацией и маленькими естественными паузами. Не как диктор, не как робот, "
    "не театрально. Русский произноси натурально. Английские слова произноси с чистым "
    "английским произношением, даже если вся фраза на русском. Говори бодро, но спокойно; "
    "фразы короткие, голос с ощущением улыбки."
)


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


def _needs_russian_repair(last_user_text: str, reply_text: str) -> bool:
    return _has_cyrillic(last_user_text) and bool(reply_text.strip()) and not _has_cyrillic(reply_text)


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
    activity_menu: str,
    lesson_loop: str,
) -> str:
    return f"""Ты — живой голосовой AI-репетитор английского для ребенка. Отвечай быстро, тепло, по теме и только финальной устной репликой.

Контекст: имя {user_name or "друг"}; возраст {age}; уровень {level}; цель {goal}; интересы {topics}; свежие темы {topic_suggestions}; язык последней реплики {language}.
Последняя реплика ребенка: {last_user_text or "пусто"}.
Недавно ребенок говорил: {recent_user_messages}. Ты отвечал: {recent_assistant_messages}.

Жесткие правила:
- 1-3 короткие фразы, максимум 220 символов. Без markdown, списков, анализа и лекций.
- Сначала ответь на реальный смысл последней реплики. Не уводи в заготовленную тему.
- Русский запрос, “не понимаю”, “что?”, “переведи”, “помоги”, “?” -> отвечай по-русски. Вставь максимум одну короткую английскую фразу.
- Английский запрос -> отвечай простым английским. Одну ошибку исправь мягко, коротко по-русски.
- Смешанный язык -> выбирай язык, на котором ребенку явно легче.
- Один ответ = одно маленькое действие: повторить 2-5 слов, выбрать один вариант, назвать одно слово или yes/no.
- Один вопрос максимум. Не тестируй каждый ход.
- Не говори шаблонно про animals/colors/story. Не повторяй одну тему подряд.
- Темы только безопасные детские. {avoid_topics}

Стиль: как репетитор рядом, который реально слушает: живо, спокойно, с поддержкой, без официоза. Для 5-10 лет больше игры и выбора; для подростков — реальные ситуации и диалоги.

Методика: {lesson_loop}. Форматы меняй: {activity_menu}. Веди мини-сцену 2-5 ходов, если ребенок не просит сменить тему. Иногда верни одно старое слово для повторения.

Микро-шаблоны:
Русский: “Понял. Проще: say ‘I like games’. Повтори: I like games.”
Одно слово: “Great! Say: I like cats. Black cats or white cats?”
Ошибка: “Good try! Лучше: I have a dog. Скажи: I have a dog.”
Вопрос: “Да, apple — это яблоко. Скажи: I want an apple.”
Игра: “Давай! It is yellow and sweet. Banana or lemon?”

Звучать должно как живой короткий ответ человеку, а не как урок из учебника."""


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
        return _voice_module_prompt(
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
            activity_menu=str(activity_menu),
            lesson_loop=str(lesson_loop),
        )
    voice_rules = (
        "Режим сейчас: ГОЛОС. Отвечай как живой человек в короткой живой беседе: 2-4 короткие фразы, "
        "сначала по сути реплики ребенка, затем одна полезная английская фраза или микро-задание. "
        "Без списков, markdown и длинных объяснений. Желательно до 220 символов."
    )
    chat_rules = (
        "Режим сейчас: ЧАТ. Можно дать чуть больше текста, но все равно коротко и по-детски: "
        "не больше 4 коротких предложений, без markdown, если ученик не просит подробный урок."
    )
    return f"""Дополнительные обязательные правила для текущего ответа.

Ученик: {user_name or "друг"}.
Возраст ученика: {age}.
Последняя реплика ученика: {last_user_text or "пусто"}.
Определенный язык последней реплики: {language}.
Свежие темы на выбор, если ребенок сам не задал тему: {topic_suggestions}.
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
- Дай ребенку очень маленький следующий шаг: повторить 2-5 слов, выбрать один вариант, назвать одно слово или ответить yes/no.
- Если в недавней истории есть слово или фраза, иногда верни ее как легкое повторение. Не делай это в каждом ответе.

Как слушать и вести диалог:
- Сначала отвечай на то, что ребенок реально спросил или попросил. Не уводи разговор в заготовленную тему.
- Если ребенок выбрал тему, продолжай ее 2-4 реплики как мини-сцену, а не сбрасывай разговор каждый раз.
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


async def synthesize_speech(text: str, mode: str = "chat") -> bytes:
    """Generates a short MP3 tutor voice response."""
    if _client is None:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    clean_text = " ".join((text or "").split())
    if not clean_text:
        raise ValueError("Text is empty")
    max_chars = 420 if mode == "voice" else 900
    if len(clean_text) > max_chars:
        clean_text = clean_text[:max_chars]

    has_russian = _has_cyrillic(clean_text)
    has_english = _has_latin(clean_text)
    if has_russian and has_english:
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

    async def create_audio(model: str, include_instructions: bool = True) -> bytes:
        request = {
            "model": model,
            "voice": voice,
            "input": clean_text,
            "response_format": "mp3",
            "speed": 1.02 if mode == "voice" else 1.0,
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
        max_output_tokens = min(CHAT_MAX_TOKENS, 170) if mode == "voice" else CHAT_MAX_TOKENS
        runtime_instructions = _runtime_instructions(user_name, age_label, prompt_context, last_user_text)
        use_stored_prompt = bool(OPENAI_PROMPT_ID and (mode != "voice" or OPENAI_PROMPT_FOR_VOICE))
        request = {
            "model": OPENAI_MODEL,
            "input": history,
            "max_output_tokens": max_output_tokens,
            "instructions": runtime_instructions,
        }
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
        reasoning_effort = "low" if mode == "voice" else OPENAI_REASONING_EFFORT
        if reasoning_effort and _supports_reasoning(OPENAI_MODEL):
            request["reasoning"] = {"effort": reasoning_effort}

        response = await _client.responses.create(**request)
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        total_tokens = _usage_int(usage, "total_tokens") or input_tokens + output_tokens
        text = (response.output_text or "").strip() or "…"

        if _needs_russian_repair(last_user_text, text):
            repair_response = await _client.responses.create(
                model=OPENAI_MODEL,
                input=[{
                    "role": "user",
                    "content": (
                        "Ученик написал по-русски, а ответ получился не на русском.\n"
                        f"Реплика ученика: {last_user_text}\n"
                        f"Ответ, который нужно переписать: {text}\n\n"
                        "Перепиши ответ по-русски для ребенка 10 лет. "
                        "Оставь максимум одну простую английскую фразу для повторения. "
                        "Сделай 1-2 коротких предложения и один вопрос или выбор."
                    ),
                }],
                instructions="Ты исправляешь язык ответа детского репетитора. Ответь только финальной репликой.",
                max_output_tokens=min(max_output_tokens, 140),
            )
            repair_text = (repair_response.output_text or "").strip()
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
