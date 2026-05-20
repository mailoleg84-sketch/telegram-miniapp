"""Конфигурация бота и Mini App."""
import os

# --- Telegram бот ---
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# --- База данных ---
DB_PATH = "bot_database.db"

# --- Mini App (Telegram WebApp) ---
# Публичный HTTPS-URL приложения. Telegram открывает только HTTPS!
# Для локальной разработки используй ngrok / cloudflared.
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.example.com")

# Параметры локального aiohttp-сервера
WEBAPP_HOST = os.getenv("WEBAPP_HOST", "0.0.0.0")
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT", "8080"))

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
