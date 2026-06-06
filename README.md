# 🧒🇬🇧 AI English Tutor Kids

Telegram Mini App — персональный AI-репетитор английского для детей и подростков **5–18 лет**.
Покупатель — родитель: он видит прогресс ребёнка, результаты тестов и список выученных слов.

> Продуктовая концепция и дорожная карта — в папке [`Концепция/`](Концепция/).

---

## 🏗️ Архитектура

| Слой | Технология | Файлы |
|------|-----------|-------|
| 🤖 Бот-лаунчер | `aiogram` 3 | [`main.py`](main.py), [`handlers/start.py`](handlers/start.py) |
| 🌐 Mini App (SPA) | Vanilla JS / CSS | [`webapp/static/`](webapp/static/) |
| ⚙️ API | `aiohttp` | [`webapp/server.py`](webapp/server.py) |
| 💾 База данных | PostgreSQL (Neon) через `asyncpg` | [`database.py`](database.py) |
| 🧠 ИИ | OpenAI: Responses, TTS, Whisper, **Realtime WebRTC**, `gpt-image-1` | [`webapp/openai_service.py`](webapp/openai_service.py) |
| 🎓 Логика урока | Детерминированная машина состояний | [`webapp/lesson_engine.py`](webapp/lesson_engine.py) |
| 🔐 Авторизация | Подпись `initData` Telegram (HMAC-SHA256) + fallback | [`webapp/auth.py`](webapp/auth.py) |

Бот делает одно: даёт кнопку «📱 Открыть приложение». Всё обучение — внутри Mini App.

---

## ✨ Возможности

- 👨‍👩‍👧 Регистрация: родитель + ребёнок, возрастная группа, цель обучения
- 🎯 Возрастной **тест уровня** (5-7 / 8-10 / 11-13 / 14-18)
- 📅 **Урок дня** (4 шага) и учебный «маршрут дня»
- 📖 **Изучение слов + тест** — карточки (перевод, транскрипция, картинка, озвучка, пример) и квиз
- 🏋️ Тренировки (выбор перевода / ввод слова), режим работы над ошибками
- 🎮 Игра «Словесная охота»
- 🗣️ **Голосовой репетитор** — Realtime WebRTC + надёжный hybrid-fallback (Whisper → чат → TTS)
- 📚 Словарь ребёнка со статусами (учим / повторить / выучено) и повторением
- 🏅 Достижения, серии дней, история занятий, рейтинг
- 👪 **Родительский отчёт** с рекомендациями
- 🛡️ Детерминированный safety-guard детских ответов
- 🛠️ Защищённая админ-панель (`ADMIN_USER_IDS`)

---

## 🚀 Локальная разработка

### 0. Требования
- Python 3.10+
- Строка подключения PostgreSQL (Neon) — `DATABASE_URL`
- Токен бота от [@BotFather](https://t.me/BotFather)
- Ключ OpenAI API

### 1. Установка
```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows; Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Переменные окружения
Скопируй [`.env.example`](.env.example) в `.env` и заполни как минимум `BOT_TOKEN`, `DATABASE_URL`, `OPENAI_API_KEY`.

### 3a. Запуск всего (бот + Mini App)
```bash
python main.py
```
> ⚠️ Локально бот стартует в **polling-режиме** и вызывает `delete_webhook` —
> это **снимет webhook продакшен-бота** на Render. Не запускай `main.py` с
> продакшен-токеном, пока живой бот работает на вебхуке.

### 3b. Запуск только Mini App (безопасно для прода) — для дизайна и QA
```bash
.venv\Scripts\python.exe -m tools.run_webapp_local
```
Поднимает **только** веб-сервер на `http://localhost:8080`, **без** бота и
**без** касания webhook. Бота не трогает.

Чтобы открыть Mini App в обычном браузере (вне Telegram нет `initData`),
нужна подписанная fallback-авторизация в query-параметрах URL:
`?fa_user_id=...&fa_first_name=...&fa_auth_date=...&fa_hash=...`
(подпись считается тем же `BOT_TOKEN`, см. [`webapp/auth.py`](webapp/auth.py)).

### 4. Тесты и статические проверки
```bash
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m py_compile config.py database.py webapp\server.py webapp\openai_service.py webapp\lesson_engine.py
node --check webapp\static\app.js
```

---

## ☁️ Деплой (Render)

- Web Service на Render (Docker), регион Ohio, **авто-деплой при push в `main`**.
- На Render бот работает в **webhook-режиме** (`BOT_RUN_MODE=webhook`).
- База — отдельный проект **Neon** (PostgreSQL).
- Конфигурация переменных — вкладка *Environment* в дашборде Render
  (файл [`render.yaml`](render.yaml) — для документации).

---

## ⚙️ Ключевые переменные окружения

| Переменная | Назначение |
|-----------|------------|
| `BOT_TOKEN` | Токен Telegram-бота |
| `DATABASE_URL` | Строка подключения Neon (`postgresql://…?sslmode=require`) |
| `WEBAPP_URL` | Публичный HTTPS-URL Mini App |
| `OPENAI_API_KEY` | Ключ OpenAI |
| `OPENAI_MODEL` | Модель чата (по умолчанию `gpt-5.4-mini`) |
| `ADMIN_USER_IDS` | Telegram id админов (через запятую) для `/diag`, `/openai_test` и админ-панели |
| `BOT_RUN_MODE` | `webhook` (Render) или `polling` (локально) |
| `API_RATE_LIMIT_PER_MINUTE` / `AI_RATE_LIMIT_PER_MINUTE` | Лимиты запросов |

Полный список и значения по умолчанию — в [`config.py`](config.py) и [`.env.example`](.env.example).

---

## 🔐 Авторизация

Telegram передаёт в Mini App `window.Telegram.WebApp.initData`. Фронтенд кладёт
её в заголовок `X-Telegram-Init-Data`, бэкенд проверяет подпись HMAC-SHA256 с
ключом `HMAC("WebAppData", BOT_TOKEN)`. Для случаев, когда Telegram не отдал
`initData` (desktop/браузер), есть короткоживущая подписанная fallback-ссылка
(заголовок `X-App-Fallback-Auth`). Без `BOT_TOKEN` запрос подделать нельзя.

---

## 📦 Зависимости

`aiogram` · `aiohttp` · `asyncpg` · `openai` · `pronouncing` — см. [`requirements.txt`](requirements.txt).

---

## 📄 Документация

- [`Концепция/`](Концепция/) — продуктовая концепция, roadmap, карта функций
- [`VOICE_TUTOR_ARCHITECTURE.md`](VOICE_TUTOR_ARCHITECTURE.md) — архитектура голосового репетитора
- [`VOICE_QA_CHECKLIST.md`](VOICE_QA_CHECKLIST.md) — чек-лист QA голоса
- [`QA_REPORT.md`](QA_REPORT.md) — отчёт по безопасности и открытым задачам
