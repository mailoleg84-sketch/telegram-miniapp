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
APP_VERSION = _env("APP_VERSION", "20260529-kids-v14")

WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# Render задаёт порт через переменную PORT — читаем её, иначе 8080.
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8080")))

# --- OpenAI API ---
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-5-nano")
OPENAI_PROMPT_ID = _env("OPENAI_PROMPT_ID", "")
OPENAI_PROMPT_VERSION = _env("OPENAI_PROMPT_VERSION", "")
OPENAI_TRANSCRIBE_MODEL = _env("OPENAI_TRANSCRIBE_MODEL", "whisper-1")
OPENAI_TTS_MODEL = _env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = _env("OPENAI_TTS_VOICE", "nova")
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "minimal")
CHAT_HISTORY_LIMIT = int(os.getenv("CHAT_HISTORY_LIMIT", "8"))
CHAT_MAX_TOKENS = int(os.getenv("CHAT_MAX_TOKENS", "240"))
AI_DAILY_MESSAGE_LIMIT = int(os.getenv("AI_DAILY_MESSAGE_LIMIT", "0"))
OPENAI_INPUT_COST_PER_1M = float(os.getenv("OPENAI_INPUT_COST_PER_1M", "0.05"))
OPENAI_OUTPUT_COST_PER_1M = float(os.getenv("OPENAI_OUTPUT_COST_PER_1M", "0.40"))

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
