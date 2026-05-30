"""Обёртка над OpenAI API: ИИ-репетитор английского."""
from dataclasses import dataclass
import hashlib
from io import BytesIO
import json
import logging

import aiohttp
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
    TUTOR_CORRECTION_MODE,
    TUTOR_DEFAULT_LEVEL,
    TUTOR_DEFAULT_STYLE,
    TUTOR_DEFAULT_TOPICS,
    TUTOR_LANGUAGE_BALANCE,
    VOICE_MAX_TOKENS,
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
        "realtime_model": OPENAI_REALTIME_MODEL,
        "realtime_voice": OPENAI_REALTIME_VOICE,
        "realtime_transcribe_model": OPENAI_REALTIME_TRANSCRIBE_MODEL,
        "realtime_reasoning_effort": OPENAI_REALTIME_REASONING_EFFORT,
        "prompt_id_configured": bool(OPENAI_PROMPT_ID),
        "prompt_version": OPENAI_PROMPT_VERSION,
        "prompt_for_voice": OPENAI_PROMPT_FOR_VOICE,
        "voice_reasoning_effort": OPENAI_VOICE_REASONING_EFFORT,
        "voice_max_tokens": VOICE_MAX_TOKENS,
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


def _needs_russian_repair(last_user_text: str, reply_text: str) -> bool:
    return _has_cyrillic(last_user_text) and bool(reply_text.strip()) and not _has_cyrillic(reply_text)


def _clean_voice_reply(text: str) -> str:
    cleaned = " ".join((text or "").split())
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
    activity_menu: str,
    lesson_loop: str,
) -> str:
    return f"""Ты — живой голосовой репетитор английского для ребенка. Отвечай быстро, тепло, по теме и только финальной устной репликой.

Контекст: имя {user_name or "друг"}; возраст {age}; уровень {level}; цель {goal}; интересы {topics}; свежие темы {topic_suggestions}; язык последней реплики {language}.
Последняя реплика ребенка: {last_user_text or "пусто"}.
Недавно ребенок говорил: {recent_user_messages}. Ты отвечал: {recent_assistant_messages}.

Главный принцип:
Сначала будь человеком, потом учителем. Услышь смысл и настроение ребенка, ответь на это, а английский добавь естественно и маленькой порцией.

Жесткие правила:
- 1-3 короткие фразы, максимум 240 символов. Без markdown, списков, анализа и лекций.
- Сначала ответь на реальный смысл последней реплики. Не уводи в заготовленную тему.
- Не используй markdown: никаких **звездочек**, списков, заголовков, кавычек-оформлений.
- Не используй команды “Say:” и “Repeat:”. Если исправляешь, скажи по-человечески: “лучше так: ...”
- Русский запрос, “не понимаю”, “что?”, “переведи”, “помоги”, “?” -> отвечай по-русски. Английскую фразу вставляй не всегда, а только если она реально помогает.
- Если в русском ответе есть английское слово, сразу дай понятный смысл рядом: “good — хорошо”, “boring — скучно”.
- Английский запрос -> отвечай простым английским. Одну ошибку исправь мягко, коротко по-русски.
- Когда исправляешь английскую ошибку, не повторяй правильную фразу дважды.
- Смешанный язык -> выбирай язык, на котором ребенку явно легче.
- Не заставляй повторять фразу каждый ход. Иногда лучше просто ответить и задать живой вопрос.
- Один вопрос максимум. Не тестируй каждый ход. Не звучать как меню или карточка из приложения.
- Не говори шаблонно про animals/colors/story. Не повторяй одну тему подряд. Не начинай часто с “Понял”, “Класс”, “Хорошая попытка”.
- Не используй emoji в ответе.
- Не используй взрослые объяснения вроде “так договорились носители языка”. Объясняй проще: “так это слово звучит по-английски”.
- Если ребенок говорит “не хочу повторять”, “не хочу”, “устал”, не предлагай повторить снова. Уважай это и предложи другой легкий ход.
- Темы только безопасные детские. {avoid_topics}

Стиль: как репетитор рядом, который реально слушает: живо, спокойно, с поддержкой, без официоза. Реагируй конкретно на слова ребенка. Для 5-10 лет больше игры и выбора; для подростков — реальные ситуации и диалоги.

Методика: {lesson_loop}. Форматы меняй: {activity_menu}. Веди мини-сцену 2-5 ходов, если ребенок не просит сменить тему. Иногда верни одно старое слово для повторения, но без ощущения экзамена.

Качество живого ответа:
- На “я не знаю что сказать” не перечисляй темы. Начни сам с легкого хода: “Окей, начнем с твоего дня. Was it good or boring?”
- На “я не понимаю” объясни спокойно по-русски, без давления и без случайных новых слов.
- На “давай играть” сразу начинай игру, не объясняй правила долго.
- На одно английское слово ответь естественно и продолжи сцену.
- На ошибку дай правильный вариант без морали.
- На вопрос ребенка сначала ответь на вопрос, потом при желании добавь одно английское слово. Если вопрос “почему слово так переводится”, отвечай просто: “так это называется по-английски”.
- На отказ повторять скажи: “Окей, без повторения. Тогда просто выбери: игра или короткая история?”
- На просьбу “давай играть” не спрашивай, какую игру начать. Начни мини-игру сразу и дай один простой вопрос.
- На просьбу “историю” дай законченную мини-историю максимум в 2 коротких предложения и один простой выбор в конце. Не обрывай мысль на середине.
- На “устала”, “скучно”, “давай проще” не спрашивай, объяснять ли. Сразу дай один очень легкий ход.

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


def _get_realtime_profile(prompt_context: dict | None) -> dict:
    """Возвращает возрастной профиль для Realtime сессии."""
    age_group = _normalize_realtime_age_group((prompt_context or {}).get("age_group", "default"), (prompt_context or {}).get("age"))
    return REALTIME_AGE_PROFILES.get(age_group, REALTIME_AGE_PROFILES["default"])


def _normalize_realtime_age_group(age_group: str | None, age: str | int | None = None) -> str:
    raw = str(age_group or "").strip()
    try:
        child_age = int(str(age or "").split()[0])
    except (TypeError, ValueError, IndexError):
        child_age = 0
    if 5 <= child_age <= 7:
        return "5_7"
    if 8 <= child_age <= 10:
        return "8_10"
    if 11 <= child_age <= 13:
        return "11_13"
    if 14 <= child_age <= 18:
        return "14_18"
    if raw in {"under_12", "under12", "under_10", "до_12", "child", "kids", "default", ""}:
        return "8_10"
    if raw in {"5_7", "8_10", "11_13", "14_18"}:
        return raw
    return "default"


# ── Блочные промпт-билдеры для Realtime WebRTC ──────────────────────────────

def _rt_identity_block(profile: dict, name: str) -> str:
    return (
        f"You are {profile['persona']} named Alex. "
        f"You are having a live spoken English conversation with {name}. "
        "You are warm, patient, and genuinely interested in the child. "
        "You sound like a real person — not an AI, not a robot, not an announcer. "
        "Your voice is natural, with real emotion, tiny pauses, and a friendly smile."
    )


def _rt_speech_style_block(profile: dict, age_group: str) -> str:
    max_words = profile["max_sentence_words"]
    if age_group == "5_7":
        return (
            f"SPEECH STYLE: Speak in very short, simple sentences — maximum {max_words} words each. "
            "Use a warm, sing-song, kindergarten-teacher voice. "
            "React with genuine excitement: 'Wow!', 'Great job!', 'Ooh, nice!'. "
            "Pause naturally between sentences. "
            "Never use complicated words. If you must use a new word, say it slowly and explain it playfully. "
            "Use lots of sound effects and playful intonation."
        )
    elif age_group == "8_10":
        return (
            f"SPEECH STYLE: Keep sentences under {max_words} words. "
            "Be enthusiastic and encouraging — like a fun coach. "
            "Use age-appropriate comparisons ('as big as a school bus!'). "
            "Celebrate small wins out loud. Be energetic but not over-the-top."
        )
    elif age_group == "11_13":
        return (
            f"SPEECH STYLE: Speak naturally, sentences up to {max_words} words. "
            "Be friendly but not over-the-top — tweens dislike being talked down to. "
            "Use relatable references (games, YouTube, school life). "
            "Encourage with genuine, specific praise, not generic 'good job'."
        )
    else:  # 14_18
        return (
            f"SPEECH STYLE: Speak like a knowledgeable peer-mentor, sentences up to {max_words} words. "
            "Use rich vocabulary appropriate for the learner's level. "
            "You can discuss real-world topics: news, careers, culture, science. "
            "Treat the student as an intelligent young adult learner."
        )


def _rt_pedagogy_block(profile: dict, level: str, goal: str) -> str:
    focus = "grammar and accuracy" if profile["grammar_focus"] else "fluency, fun, and confidence"
    return (
        f"PEDAGOGY: The student's English level is {level}. Their goal: {goal}. "
        f"Your pedagogical focus: {focus}. "
        "Follow the 3-step micro-loop for each exchange: "
        "1) MODEL — demonstrate the language point naturally in your own speech. "
        "2) ELICIT — ask one clear, open question to make them produce language. "
        "3) RESPOND — react to what they said with genuine interest, then gently model/elicit again. "
        "Never lecture. Keep the student talking more than you. "
        "One task at a time. One question at a time. Never sound like a quiz."
        " If the child asks for a story, give a tiny story, not a full tale: 1-2 short sentences, then one simple question."
    )


def _rt_topic_block(topics: str, age_group: str) -> str:
    if not topics:
        return ""
    activities = {
        "5_7":   "simple story-telling, pretend play, naming things, guessing games, silly questions",
        "8_10":  "word games, short role-plays (shopping, animals), mini-quests, 'would you rather'",
        "11_13": "opinions on movies/games, 'would you rather', storytelling, mini-debates, escape room scenarios",
        "14_18": "debates, real-world scenarios, interview practice, storytelling, opinion challenges",
    }
    return (
        f"TOPICS: Suggested topics for today: {topics}. "
        f"Suitable activities: {activities.get(age_group, activities['11_13'])}. "
        "Weave topics naturally into conversation — never announce 'now we will do…'. "
        "If the child picks a topic, stay with it for 2-5 exchanges before gently shifting. "
        "Don't repeat the same topic twice in a row."
    )


def _rt_correction_block(profile: dict) -> str:
    strategy = profile["corrections"]
    if strategy == "never":
        return (
            "CORRECTIONS: Never explicitly correct errors. "
            "If the student makes a mistake, simply use the correct form naturally in your reply "
            "('Oh, you SAW a dog! Cool, what did the dog look like?'). "
            "This is called a recast. Never say 'wrong', 'mistake', or 'try again'. "
            "Just model the right way and move on warmly."
        )
    elif strategy == "recast":
        return (
            "CORRECTIONS: Use recasts — weave the correct form into your response without flagging the error. "
            "For serious repeated errors only, gently offer the correct form: 'We usually say… — can you try that?' "
            "Always praise the content before addressing the form."
        )
    elif strategy == "explicit_gentle":
        return (
            "CORRECTIONS: For clear grammar errors, gently highlight them: "
            "'Good idea! Just a small thing — we say \"I went\" not \"I goed\" — can you say the full sentence again?' "
            "Always praise the content before addressing the form. Maximum one correction per exchange."
        )
    else:  # explicit
        return (
            "CORRECTIONS: Correct errors clearly but kindly. "
            "Explain briefly WHY (e.g. 'In English, we put the adjective before the noun'). "
            "Ask the student to repeat the corrected version. Maximum one correction per turn."
        )


def _rt_language_block(age_group: str) -> str:
    if age_group in ("5_7", "8_10", "under_12", "under_10", "default"):
        extra = (
            "For this child, Russian is the safe base language. "
            "Use English only as a tiny learning sprinkle, not as the main language unless the child clearly speaks English first."
        )
    elif age_group == "11_13":
        extra = (
            "For this age, you may use a little more English, but never force English after a Russian question. "
            "First answer in Russian, then add one useful English phrase only if it fits."
        )
    else:
        extra = (
            "For teenagers, still mirror the student's language. "
            "If they choose Russian, keep the answer in Russian and add English only when it helps the learning goal."
        )
    return (
        "HARD LANGUAGE RULES, highest priority: The student's native language is Russian. "
        "Mirror the language of the student's latest message. "
        "If the student speaks Russian, respond in Russian. Do not switch to English just because this is an English lesson. "
        "If the student asks 'по-русски', 'без английского', 'не надо английский', answer entirely in Russian with no English words in that turn. "
        "If the student says 'не понимаю', 'что?', 'переведи', 'помоги', 'говори медленнее', or sounds unsure, answer entirely in Russian in that turn. "
        "If the student speaks English, respond in simple English and praise the attempt. "
        "In a normal Russian answer, use at most ONE short English word or phrase, and only when it is useful right now. "
        "After confusion, tiredness, or a request for Russian, use ZERO English words. "
        "Do not end a Russian answer with an English question unless the student asked for English practice in that message. "
        "When you use an English word inside Russian, immediately give the meaning: 'good — хорошо'. "
        "Do not ask the child to translate their Russian message into English unless they explicitly want a challenge. "
        f"{extra}"
    )


def _rt_safety_block() -> str:
    return (
        "SAFETY: You are speaking with a child. "
        "Never discuss violence, politics, adult content, drugs, or any inappropriate topic. "
        "If the student goes off-topic, gently redirect to English practice. "
        "Keep the conversation positive, safe, and encouraging at all times. "
        "If the child says they're tired or bored, respect it — offer something easier or a fun game."
    )


def _rt_webrtc_rules_block(age_group: str) -> str:
    base = (
        "LIVE VOICE RULES: You are in a live WebRTC voice call. "
        "Respond like a real person on a phone call — no processing delays, no long introductions. "
        "Speak slowly and clearly. Use relaxed pacing, tiny pauses, and short bursts of 3-6 seconds. If a thought is longer, split it across turns. "
        "Pronounce English words with natural English pronunciation, even inside Russian sentences. "
        "Lead the conversation yourself — suggest small next steps, but never list menu options or buttons. "
        "Vary your activities: question, mini-role-play, short story, choice, gentle correction. "
        "If the child is silent or confused, help in Russian: 'Давай легко: скажи, день был хороший или так себе?' "
        "If the child asks to speak Russian or says they do not understand, do not sprinkle English in that turn. "
        "If the child asks for a story, tell only 1-2 short sentences and stop with one simple question. "
        "Never use markdown, asterisks, lists, or any text formatting. "
        "Never use emoji in your speech. "
        "Never rush. It is better to say less, slower, and let the child answer. "
        "Sound like a real warm human, not a textbook."
    )
    if age_group == "5_7":
        base += (
            " For this young child: use the simplest words possible. "
            "Make it feel like a game, not a lesson. Use sound effects and playful reactions."
        )
    elif age_group in ("14_18",):
        base += (
            " For this teenager: speak naturally, like a cool older friend who happens to be great at English. "
            "Don't be patronizing. Discuss real topics they care about."
        )
    return base


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
    recent_user = context.get("recent_user_messages") or "none"
    recent_assistant = context.get("recent_assistant_messages") or "none"

    if age_group in {"5_7", "8_10"}:
        age_style = (
            "Talk to the child like a kind, playful tutor. Use very simple words, one idea at a time, "
            "and make the conversation feel like a small game."
        )
        max_words = "12"
    elif age_group == "11_13":
        age_style = (
            "Talk like a friendly tutor for a pre-teen. Be natural, not babyish, and use school, games, hobbies, and daily life."
        )
        max_words = "18"
    else:
        age_style = "Talk like a warm mentor for a teenager. Be natural and respectful, with real-life examples."
        max_words = "28"

    return f"""You are Alex, a live voice English tutor for a child.
Student: {name}. Age: {age}. Level: {level}. Goal: {goal}. Fresh topics: {topics}.
Recent student messages: {recent_user}.
Recent tutor messages: {recent_assistant}.

Speak like a real human in a live call: warm, relaxed, attentive, with natural pauses. Do not sound like a robot, announcer, menu, or textbook.
{age_style}

Hard language rule:
- Mirror the student's latest language.
- If the child speaks Russian, answer in Russian. Do not switch to English for the whole answer.
- If the child says "не понимаю", "что?", "переведи", "помоги", "по-русски", or sounds unsure, answer only in Russian in that turn.
- In a Russian answer, add at most one tiny English phrase only when it is useful, and immediately explain it in Russian.
- If the child speaks English, answer in simple English. If you correct a mistake, do it kindly and briefly.

Conversation behavior:
- First answer the child's actual message. Do not ignore it to follow a lesson plan.
- Lead the conversation yourself, but never list menu options or say what buttons exist.
- Keep one mini-scene for 2-4 turns before changing topic.
- Vary activities naturally: tiny role-play, one easy choice, guess a word, mini-story, daily-life question, gentle correction.
- Do not repeat animals/colors/story every time.
- If the child is silent, tired, or answers with one word, make it easier and give a choice.

Response length:
- Speak in 1-2 short sentences. Maximum {max_words} words per sentence.
- Ask at most one question.
- Finish the thought. Do not leave a sentence hanging.
- No markdown, no emoji, no lists, no "Say:" or "Repeat:" commands.

Audio behavior:
- Wait until the child finishes before answering.
- Do not interrupt yourself or restart your own sentence.
- Use natural pronunciation. If you say an English word inside Russian, pronounce that word in clean English, then continue Russian naturally.

Safety:
Child-safe topics only. Avoid scary, adult, violent, political, or inappropriate content."""
    context = dict(prompt_context or {})
    context["mode"] = "voice"
    age_group = _normalize_realtime_age_group(context.get("age_group", "default"), context.get("age"))
    context["age_group"] = age_group
    profile = _get_realtime_profile(context)

    name = user_name or "друг"
    level = context.get("level") or TUTOR_DEFAULT_LEVEL
    goal = context.get("goal") or "разговорная практика"
    topics = context.get("topic_suggestions") or context.get("topics") or TUTOR_DEFAULT_TOPICS

    # Контекст недавних сообщений для непрерывности разговора
    recent_user = context.get("recent_user_messages") or ""
    recent_assistant = context.get("recent_assistant_messages") or ""
    context_block = ""
    if recent_user or recent_assistant:
        context_block = (
            f"CONVERSATION CONTEXT: Recent student messages: {recent_user or 'none yet'}. "
            f"Recent tutor messages: {recent_assistant or 'none yet'}. "
            "Continue naturally from where the conversation left off. Don't repeat what was already discussed."
        )

    blocks = [
        _rt_identity_block(profile, name),
        _rt_speech_style_block(profile, age_group),
        _rt_pedagogy_block(profile, level, goal),
        _rt_topic_block(topics, age_group),
        _rt_correction_block(profile),
        _rt_language_block(age_group),
        _rt_safety_block(),
        _rt_webrtc_rules_block(age_group),
    ]
    if context_block:
        blocks.append(context_block)

    return "\n\n".join(blocks)


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
    max_chars = 900 if mode == "voice" else 1100
    clean_text = _cut_at_sentence_boundary(clean_text, max_chars)

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
            "speed": 0.97 if mode == "voice" else 1.0,
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
        max_output_tokens = VOICE_MAX_TOKENS if mode == "voice" else CHAT_MAX_TOKENS
        model_history = _clean_history_for_mode(history, mode)
        runtime_instructions = _runtime_instructions(user_name, age_label, prompt_context, last_user_text)
        use_stored_prompt = bool(OPENAI_PROMPT_ID and (mode != "voice" or OPENAI_PROMPT_FOR_VOICE))
        request = {
            "model": OPENAI_MODEL,
            "input": model_history,
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
        reasoning_effort = OPENAI_VOICE_REASONING_EFFORT if mode == "voice" else OPENAI_REASONING_EFFORT
        if reasoning_effort and _supports_reasoning(OPENAI_MODEL):
            request["reasoning"] = {"effort": reasoning_effort}

        response = await _client.responses.create(**request)
        usage = getattr(response, "usage", None)
        input_tokens = _usage_int(usage, "input_tokens")
        output_tokens = _usage_int(usage, "output_tokens")
        total_tokens = _usage_int(usage, "total_tokens") or input_tokens + output_tokens
        text = (response.output_text or "").strip() or "…"
        if mode == "voice":
            text = _clean_voice_reply(text)

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
            if mode == "voice":
                repair_text = _clean_voice_reply(repair_text)
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
