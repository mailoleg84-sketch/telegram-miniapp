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


def _env_int(name: str, default: int) -> int:
    """Числовой env: пустая строка/пробелы/мусор -> default (а не ValueError).
    Render может хранить переменную пустой ('') -> голый int(os.getenv()) ронял
    импорт приложения на старте деплоя (Exited status 1)."""
    raw = (os.getenv(name) or "").strip().strip('"').strip("'")
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _env_float(name: str, default: float) -> float:
    """То же, что _env_int, для float-параметров (стоимости/лимиты OpenAI)."""
    raw = (os.getenv(name) or "").strip().strip('"').strip("'")
    try:
        return float(raw)
    except ValueError:
        return float(default)

# --- Telegram бот ---
BOT_TOKEN = _env("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
BOT_RUN_MODE = _env("BOT_RUN_MODE", "webhook" if (os.getenv("RENDER") or os.getenv("PORT")) else "polling")
WEBHOOK_PATH = _env("WEBHOOK_PATH", "/telegram/webhook")
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET", "")
ADMIN_USER_IDS = {
    int(part)
    for part in _env("ADMIN_USER_IDS", "").replace(";", ",").split(",")
    if part.strip().isdigit()
}

# --- База данных (PostgreSQL / Neon) ---
# Строка подключения вида: postgresql://user:pass@host/dbname?sslmode=require
DATABASE_URL = _env("DATABASE_URL", "")

# --- Redis (опционально: rate-limit и токены тренировок) ---
# Если задан (например Upstash rediss://...) — лимиты и одноразовые токены живут
# в Redis (переживают рестарт, общие для инстансов). Иначе — in-memory в процессе.
REDIS_URL = _env("REDIS_URL", "")

# --- Mini App (Telegram WebApp) ---
WEBAPP_URL = _env("WEBAPP_URL", "https://telegram-miniapp-1-r0sj.onrender.com")
APP_VERSION = _env("APP_VERSION", "20260624-kids-v153")

# --- Напоминания ботом (ежедневная рассылка, opt-in) ---
# Триггерится внешним cron (GitHub Actions) -> POST /internal/send-reminders с
# заголовком X-Cron-Secret. Если секрет пустой — эндпоинт выключен (fail-closed),
# рассылки нет. Задайте одинаковое значение в Render и в GitHub Secrets.
REMINDER_CRON_SECRET = _env("REMINDER_CRON_SECRET", "")
# Напоминаем только тем, кто был активен за последние N дней (не теребим ушедших).
REMINDER_ACTIVITY_WINDOW_DAYS = _env_int("REMINDER_ACTIVITY_WINDOW_DAYS", 14)

# Уровень логирования (DEBUG/INFO/WARNING/ERROR) — управляем из окружения.
LOG_LEVEL = _env("LOG_LEVEL", "INFO").upper()

WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# Render задаёт порт через переменную PORT — читаем её, иначе 8080.
WEBAPP_PORT = _env_int("PORT", _env_int("WEBAPP_PORT", 8080))

# --- OpenAI API ---
OPENAI_API_KEY = _env("OPENAI_API_KEY", "")
OPENAI_MODEL = _env("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_PROMPT_ID = _env("OPENAI_PROMPT_ID", "")
OPENAI_PROMPT_VERSION = _env("OPENAI_PROMPT_VERSION", "")
OPENAI_PROMPT_FOR_VOICE = _env("OPENAI_PROMPT_FOR_VOICE", "0").lower() in {"1", "true", "yes", "on"}
OPENAI_TRANSCRIBE_MODEL = _env("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_TTS_MODEL = _env("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = _env("OPENAI_TTS_VOICE", "coral")
_RAW_OPENAI_VOICE_TTS_VOICE = _env("OPENAI_VOICE_TTS_VOICE", "")
OPENAI_VOICE_TTS_VOICE = "coral" if _RAW_OPENAI_VOICE_TTS_VOICE.lower() in {"", "marin", "cedar"} else _RAW_OPENAI_VOICE_TTS_VOICE
_RAW_OPENAI_REALTIME_MODEL = _env("OPENAI_REALTIME_MODEL", "")
OPENAI_REALTIME_MODEL = "gpt-realtime-2" if _RAW_OPENAI_REALTIME_MODEL.lower() in {"", "gpt-realtime", "gpt-realtime-mini"} else _RAW_OPENAI_REALTIME_MODEL
_RAW_OPENAI_REALTIME_VOICE = _env("OPENAI_REALTIME_VOICE", "")
OPENAI_REALTIME_VOICE = "coral" if _RAW_OPENAI_REALTIME_VOICE.lower() in {"", "marin", "cedar"} else _RAW_OPENAI_REALTIME_VOICE
OPENAI_REALTIME_TRANSCRIBE_MODEL = _env("OPENAI_REALTIME_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
OPENAI_IMAGE_MODEL = _env("OPENAI_IMAGE_MODEL", "gpt-image-1")
OPENAI_IMAGE_SIZE = _env("OPENAI_IMAGE_SIZE", "1024x1024")
OPENAI_IMAGE_QUALITY = _env("OPENAI_IMAGE_QUALITY", "medium")
OPENAI_IMAGE_FORMAT = _env("OPENAI_IMAGE_FORMAT", "png")
OPENAI_IMAGE_VISION_MODEL = _env("OPENAI_IMAGE_VISION_MODEL", OPENAI_MODEL)
OPENAI_IMAGE_MAX_RETRIES = _env_int("OPENAI_IMAGE_MAX_RETRIES", 1)
# Авто-генерация платных gpt-image-1 картинок для слов. По умолчанию ВЫКЛ:
# карточки используют бесплатные эмодзи + SVG-сцены. Включить = "1"/"true".
VOCAB_AI_IMAGES = _env("VOCAB_AI_IMAGES", "0").lower() in {"1", "true", "yes", "on"}
# Бесплатные фото для слов (Pixabay). По умолчанию ВЫКЛ: для детского словаря
# фотосток ненадёжен — показывает связанный объект/действие, а не значение слова
# (lesson -> рука с карандашом, answer -> заполнение анкеты). Даже при "1" фото
# отдаётся ТОЛЬКО для слов из allowlist PHOTO_SAFE_OBJECTS (однозначные конкретные
# предметы) — см. allows_free_photo. Для учебного режима держим выключенным.
VOCAB_FREE_PHOTOS = _env("VOCAB_FREE_PHOTOS", "0").lower() in {"1", "true", "yes", "on"}
# Бесплатный ключ Pixabay (https://pixabay.com/api/docs/). Задаётся в Render env.
PIXABAY_API_KEY = _env("PIXABAY_API_KEY", "")
OPENAI_REASONING_EFFORT = _env("OPENAI_REASONING_EFFORT", "medium")
OPENAI_VOICE_REASONING_EFFORT = _env("OPENAI_VOICE_REASONING_EFFORT", "low")
OPENAI_REALTIME_REASONING_EFFORT = _env("OPENAI_REALTIME_REASONING_EFFORT", "low")
CHAT_HISTORY_LIMIT = _env_int("CHAT_HISTORY_LIMIT", 8)
# Ретенция истории чата: храним последние N сообщений на пользователя, старше —
# чистим при записи (таблица conversations иначе растёт без предела). Приложение
# читает максимум CHAT_HISTORY_LIMIT*2, так что 50 — с большим запасом. 0 = выкл.
CHAT_RETENTION_PER_USER = _env_int("CHAT_RETENTION_PER_USER", 50)
CHAT_MAX_TOKENS = _env_int("CHAT_MAX_TOKENS", 240)
VOICE_MAX_TOKENS = _env_int("VOICE_MAX_TOKENS", 400)
AI_DAILY_MESSAGE_LIMIT = _env_int("AI_DAILY_MESSAGE_LIMIT", 0)
# Глобальный суточный потолок расходов OpenAI по ВСЕМ пользователям (USD). Защита
# от runaway-затрат (баг/абьюз): при превышении AI-эндпоинты временно отдают
# «лимит на сегодня». 0 = выключено. Задайте в Render под свой бюджет (напр. 10).
OPENAI_DAILY_COST_LIMIT_USD = _env_float("OPENAI_DAILY_COST_LIMIT_USD", 0.0)
# Отдельный жёсткий суточный лимит на старт дорогих Realtime-сессий (per-user).
# Защищает от cost-amplification: ~$0.05 за сессию. 0 = выключено.
REALTIME_DAILY_SESSION_LIMIT = _env_int("REALTIME_DAILY_SESSION_LIMIT", 40)
# Общий бюджет на выдачу Realtime-токена (с учётом retry). Раньше два запроса по
# 25с могли держать ребёнка ~50с на «застывшем» экране. 0 = без общего лимита.
REALTIME_TOKEN_TIMEOUT_SEC = _env_int("REALTIME_TOKEN_TIMEOUT_SEC", 30)
API_RATE_LIMIT_PER_MINUTE = _env_int("API_RATE_LIMIT_PER_MINUTE", 120)
AI_RATE_LIMIT_PER_MINUTE = _env_int("AI_RATE_LIMIT_PER_MINUTE", 30)
OPENAI_INPUT_COST_PER_1M = _env_float("OPENAI_INPUT_COST_PER_1M", 0.75)
OPENAI_OUTPUT_COST_PER_1M = _env_float("OPENAI_OUTPUT_COST_PER_1M", 4.50)
# Оценочные стоимости для учёта расходов на TTS / картинки / Realtime в админке.
# Приблизительные значения для видимости трат — уточняй под свой тариф OpenAI.
OPENAI_TTS_COST_PER_1K_CHARS = _env_float("OPENAI_TTS_COST_PER_1K_CHARS", 0.015)
OPENAI_IMAGE_COST_PER_CALL = _env_float("OPENAI_IMAGE_COST_PER_CALL", 0.02)
OPENAI_REALTIME_SESSION_COST = _env_float("OPENAI_REALTIME_SESSION_COST", 0.05)

# --- Настройки репетитора для Prompt Variables ---
TUTOR_DEFAULT_LEVEL = _env("TUTOR_DEFAULT_LEVEL", "beginner")
TUTOR_DEFAULT_STYLE = _env("TUTOR_DEFAULT_STYLE", "игровой, доброжелательный, короткими репликами")
TUTOR_DEFAULT_TOPICS = _env("TUTOR_DEFAULT_TOPICS", "животные, еда, цвета, игры, школа, путешествия, истории")
TUTOR_CORRECTION_MODE = _env("TUTOR_CORRECTION_MODE", "мягко исправлять и сразу давать правильный пример")
TUTOR_LANGUAGE_BALANCE = _env("TUTOR_LANGUAGE_BALANCE", "отвечать на языке ученика; при трудности объяснять по-русски и давать простую английскую фразу")

# --- Геймификация ---
POINTS_CORRECT = 10
POINTS_WRONG = -3
GAME_POINTS_CORRECT = _env_int("GAME_POINTS_CORRECT", 8)
GAME_PERFECT_BONUS_POINTS = _env_int("GAME_PERFECT_BONUS_POINTS", 10)
DAILY_LESSON_REWARD_POINTS = _env_int("DAILY_LESSON_REWARD_POINTS", 25)
DAILY_LESSON_STEPS = 4

# --- Возрастные группы детей ---
AGE_GROUPS = [
    ("5-7 лет", "5_7"),
    ("8-10 лет", "8_10"),
    ("11-13 лет", "11_13"),
    ("14-18 лет", "14_18"),
]

# Канонические ключи возрастных групп (единый источник истины).
AGE_GROUP_KEYS = frozenset(value for _, value in AGE_GROUPS)


def age_group_from_age(age) -> str:
    """Каноническая возрастная группа из точного возраста ребёнка.

    Возвращает "" если возраст вне 5–18 (вызывающий сам решает, что делать
    дальше). Это единственная «лестница» возраст→группа в проекте — её НЕ
    дублируют в server.py / openai_service.py, а делегируют сюда.
    """
    try:
        years = int(age)
    except (TypeError, ValueError):
        return ""
    if 5 <= years <= 7:
        return "5_7"
    if 8 <= years <= 10:
        return "8_10"
    if 11 <= years <= 13:
        return "11_13"
    if 14 <= years <= 18:
        return "14_18"
    return ""

LEARNING_GOALS = [
    ("Первый английский", "first_steps"),
    ("Школьная программа", "school"),
    ("Устная практика", "speaking"),
    ("Путешествия", "travel"),
    ("Экзамены", "exams"),
]

ENGLISH_LEVELS = [
    ("Starter - первые слова", "starter"),
    ("Beginner / A1", "beginner"),
    ("Elementary / A1+", "elementary"),
    ("Pre-Intermediate / A2", "pre_intermediate"),
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
        "speed": 1.0,                 # не замедляем playback: темп задает промпт, а speed может портить тембр
        "max_output_tokens": 90,      # очень короткие ответы, внимание ребёнка ограничено
        "temperature": 0.9,           # теплее/креативнее = игривый тон
        "voice": OPENAI_REALTIME_VOICE,

        # VAD / детекция голоса — маленькие дети говорят тихо и с паузами
        "vad_threshold": 0.35,        # ниже = ловит тихий голос
        "vad_type": "semantic_vad",
        "semantic_eagerness": "low",
        "silence_duration_ms": 1200,  # 1.2 сек паузы перед ответом AI — дать договорить
        "prefix_padding_ms": 400,     # захватить начало тихой речи
        "idle_timeout_ms": 30_000,    # максимум OpenAI Realtime; дети долго думают
        "interrupt_response": False,  # не прерывать AI — малышей это путает

        # Педагогика (используется в промпт-билдере)
        "persona": "a super-friendly kindergarten teacher",
        "max_sentence_words": 7,
        "corrections": "never",       # никогда не исправлять напрямую — только recast
        "grammar_focus": False,
    },
    "8_10": {
        "speed": 1.0,
        "max_output_tokens": 120,
        "temperature": 0.85,
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.38,
        "vad_type": "semantic_vad",
        "semantic_eagerness": "low",
        "silence_duration_ms": 950,
        "prefix_padding_ms": 350,
        "idle_timeout_ms": 30_000,
        "interrupt_response": False,

        "persona": "a fun and encouraging primary-school English tutor",
        "max_sentence_words": 10,
        "corrections": "recast",      # повторить правильно без акцента на ошибке
        "grammar_focus": False,
    },
    "11_13": {
        "speed": 1.0,
        "max_output_tokens": 170,
        "temperature": 0.80,
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.40,
        "vad_type": "semantic_vad",
        "semantic_eagerness": "low",
        "silence_duration_ms": 750,
        "prefix_padding_ms": 320,
        "idle_timeout_ms": 28_000,
        "interrupt_response": False,

        "persona": "a cool and supportive middle-school English tutor",
        "max_sentence_words": 15,
        "corrections": "explicit_gentle",  # "Good try! The word is actually…"
        "grammar_focus": True,
    },
    "14_18": {
        "speed": 1.0,                 # естественный темп без спешки
        "max_output_tokens": 240,     # место для развёрнутых объяснений
        "temperature": 0.75,          # точнее, взрослее
        "voice": OPENAI_REALTIME_VOICE,

        "vad_threshold": 0.42,
        "vad_type": "semantic_vad",
        "semantic_eagerness": "medium",
        "silence_duration_ms": 600,
        "prefix_padding_ms": 300,
        "idle_timeout_ms": 22_000,
        "interrupt_response": False,

        "persona": "a knowledgeable and engaging high-school English tutor and mentor",
        "max_sentence_words": 24,
        "corrections": "explicit",    # исправлять и объяснять почему
        "grammar_focus": True,
    },
}

# Фолбэк, если age_group не определена
REALTIME_AGE_PROFILES["under_12"] = REALTIME_AGE_PROFILES["8_10"]
REALTIME_AGE_PROFILES["under_10"] = REALTIME_AGE_PROFILES["8_10"]
REALTIME_AGE_PROFILES["default"] = REALTIME_AGE_PROFILES["8_10"]
