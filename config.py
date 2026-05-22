"""Конфигурация бота и Mini App."""
import os

# --- Telegram бот ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# --- База данных (PostgreSQL / Neon) ---
# Строка подключения вида: postgresql://user:pass@host/dbname?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "")

# --- Mini App (Telegram WebApp) ---
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.example.com")

WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
# Render задаёт порт через переменную PORT — читаем её, иначе 8080.
WEBAPP_PORT = int(os.getenv("PORT", os.getenv("WEBAPP_PORT", "8080")))

# --- Claude (Anthropic API) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
CHAT_HISTORY_LIMIT = 12
CHAT_MAX_TOKENS = 500

# --- Геймификация ---
POINTS_CORRECT = 10
POINTS_WRONG = -3

# --- Возрастные группы при регистрации ---
AGE_GROUPS = [
    ("👶 До 12",  "under_12"),
    ("🧒 13–17",  "13_17"),
    ("🧑 18–25",  "18_25"),
    ("👨 26–40",  "26_40"),
    ("👴 40+",    "over_40"),
]
