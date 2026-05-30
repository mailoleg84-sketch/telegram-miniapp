"""Конфигурация бота и Mini App."""
import os
from pathlib import Path


def _load_local_env() -> None:
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env()


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, default)
    return value.strip().strip('"').strip("'")

# --- Telegram бот ---
BOT_TOKEN = _env("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BOT_RUN_MODE = _env("BOT_RUN_MODE", "webhook" if (os.getenv("RENDER") or os.getenv("PORT")) else "polling")
WEBHOOK_PATH = _env("WEBHOOK_PATH", "/telegram/webhook")
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET", "")

# --- База данных (PostgreSQL / Neon) ---
# Строка подключения вида: postgresql://user:pass@host/dbname?sslmode=require
DATABASE_URL = _env("DATABASE_URL", "")

# --- Mini App (Telegram WebApp) ---
WEBAPP_URL = _env("WEBAPP_URL", "https://telegram-miniapp-1-r0sj.onrender.com")
APP_VERSION = _env("APP_VERSION", "20260531-kids-v31")

WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# Render задаёт порт через переменную PORT — читаем её, иначе 8080.
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8080")))

# --- OpenAI API ---
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-5.4-mini")
OPENAI_PROMPT_ID = _env("OPENAI_PROMPT_ID", "")
OPENAI_PROMPT_VERSION = _env("OPENAI_PROMPT_VERSION", "")
OPENAI_PROMPT_FOR_VOICE = _env("OPENAI_PROMPT_FOR_VOICE", "0").lower() in {"1", "true", "yes", "on"}
OPENAI_TRANSCRIBE_MODEL = _env("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
OPENAI_TTS_MODEL = _env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = _env("OPENAI_TTS_VOICE", "coral")
OPENAI_VOICE_TTS_VOICE = _env("OPENAI_VOICE_TTS_VOICE", "marin")
OPENAI_REALTIME_MODEL = _env("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
OPENAI_REALTIME_VOICE = _env("OPENAI_REALTIME_VOICE", OPENAI_VOICE_TTS_VOICE or "marin")
OPENAI_REALTIME_TRANSCRIBE_MODEL = _env("OPENAI_REALTIME_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "medium")
OPENAI_VOICE_REASONING_EFFORT = _env("OPENAI_VOICE_REASONING_EFFORT", "low")
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "8"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "240"))
VOICE_MAX_TOKENS = int(os.getenv("VOICE_MAX_TOKENS", "700"))
AI_DAILY_MESSAGE_LIMIT = int(os.getenv("AI_DAILY_MESSAGE_LIMIT", "0"))
OPENAI_INPUT_COST_PER_1M = float(os.getenv("OPENAI_INPUT_COST_PER_1M", "0.75"))
OPENAI_OUTPUT_COST_PER_1M = float(os.getenv("OPENAI_OUTPUT_COST_PER_1M", "4.50"))

# --- Настройки AI-репетитора для Prompt Variables ---
TUTOR_DEFAULT_LEVEL = _env("TUTOR_DEFAULT_LEVEL", "beginner")
TUTOR_DEFAULT_STYLE = _env("TUTOR_DEFAULT_STYLE", "игровой, доброжелательный, короткими репликами")
TUTOR_DEFAULT_TOPICS = _env("TUTOR_DEFAULT_TOPICS", "животные, еда, цвета, игры, школа, путешествия, истории")
TUTOR_CORRECTION_MODE = _env("TUTOR_CORRECTION_MODE", "мягко исправлять и сразу давать правильный пример")
TUTOR_LANGUAGE_BALANCE = _env("TUTOR_LANGUAGE_BALANCE", "отвечать на языке ученика; при трудности объяснять по-русски и давать простую английскую фразу")

# --- Геймификация ---
POINTS_CORRECT = 10
POINTS_WRONG = -3
DAILY_LESSON_REWARD_POINTS = int(os.getenv("DAILY_LESSON_REWARD_POINTS", "25"))
DAILY_LESSON_STEPS = 4

# --- Возрастные группы детей ---
AGE_GROUPS = [
    ("5-7 лет", "5_7"),
    ("8-10 лет", "8_10"),
    ("11-13 лет", "11_13"),
    ("14-18 лет", "14_18"),
]

LEARNING_GOALS = [
    ("Первый английский", "first_steps"),
    ("Школьная программа", "school"),
    ("Разговорная практика", "speaking"),
    ("Путешествия", "travel"),
    ("Экзамены", "exams"),
]

WORDS_PER_AGE_GROUP = {
    "5_7": 4,
    "8_10": 6,
    "11_13": 8,
    "14_18": 10,
}

# ── Возрастные профили для Realtime WebRTC голосового режима ──────────────────
# Каждый профиль адаптирует параметры OpenAI Realtime API под возрастную группу:
# - speed: скорость речи AI (0.88 = медленнее для малышей, 1.02 = нормальная для подростков)
# - max_output_tokens: лимит длины ответа (короче для малышей, длиннее для старших)
# - temperature: креативность (выше = игривее для малышей, ниже = точнее для старших)
# - VAD: настройки детекции голоса (чувствительнее для тихих детей, длиннее паузы для думающих)
# - persona/corrections/grammar_focus: педагогические параметры для промпта
REALTIME_AGE_PROFILES = {
    "5_7": {
        # Аудио / модель
        "speed": 0.88,                # медленнее — как воспитатель в детском саду
        "max_output_tokens": 150,     # очень короткие ответы, внимание ребёнка ограничено
        "temperature": 0.9,           # теплее/креативнее = игривый тон
        "voice": OPENAI_REALTIME_VOICE,

        # VAD / детекция голоса — маленькие дети говорят тихо и с паузами
        "vad_threshold": 0.35,        # ниже = ловит тихий голос
        "silence_duration_ms": 1200,  # 1.2 сек паузы перед ответом AI — дать договорить
        "prefix_padding_ms": 400,     # захватить начало тихой речи
        "idle_timeout_ms": 45_000,    # 45 сек тишины — дети долго думают
        "interrupt_response": False,  # не прерывать AI — малышей это путает

        # Педагогика (используется в промпт-билдере)
        "persona": "a super-friendly kindergarten teacher",
        "max_sentence_words": 8,
        "corrections": "never",       # никогда не исправлять напрямую — только recast
        "grammar_focus": False,
    },
    "8_10": {
        "speed": 0.94,
        "max_output_tokens": 200,
        "temperature": 0.85,
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.38,
        "silence_duration_ms": 950,
        "prefix_padding_ms": 350,
        "idle_timeout_ms": 35_000,
        "interrupt_response": True,

        "persona": "a fun and encouraging primary-school English tutor",
        "max_sentence_words": 12,
        "corrections": "recast",      # повторить правильно без акцента на ошибке
        "grammar_focus": False,
    },
    "11_13": {
        "speed": 0.99,
        "max_output_tokens": 280,
        "temperature": 0.80,
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.40,
        "silence_duration_ms": 750,
        "prefix_padding_ms": 320,
        "idle_timeout_ms": 28_000,
        "interrupt_response": True,

        "persona": "a cool and supportive middle-school English tutor",
        "max_sentence_words": 18,
        "corrections": "explicit_gentle",  # "Good try! The word is actually…"
        "grammar_focus": True,
    },
    "14_18": {
        "speed": 1.02,                # почти нативный темп
        "max_output_tokens": 400,     # место для развёрнутых объяснений
        "temperature": 0.75,          # точнее, взрослее
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.42,
        "silence_duration_ms": 600,
        "prefix_padding_ms": 300,
        "idle_timeout_ms": 22_000,
        "interrupt_response": True,

        "persona": "a knowledgeable and engaging high-school English tutor and mentor",
        "max_sentence_words": 30,
        "corrections": "explicit",    # исправлять и объяснять почему
        "grammar_focus": True,
    },
}

# Фолбэк, если age_group не определена
REALTIME_AGE_PROFILES["default"] = REALTIME_AGE_PROFILES["11_13"]
