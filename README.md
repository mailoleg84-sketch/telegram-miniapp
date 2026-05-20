# 📱 Telegram Mini App для изучения английских слов

Полноценное приложение внутри Telegram (Telegram Web App / Mini App) +
бот-лаунчер. Раньше всё было кнопками в чате — теперь у нас:

- 🤖 **Бот** (`aiogram`) — даёт кнопку «📱 Открыть приложение»
- 🌐 **Mini App** (HTML/CSS/JS) — нативный интерфейс внутри Telegram
- ⚙️ **API** (`aiohttp`) — JSON-эндпоинты для фронта
- 💾 **SQLite** — общая база для бота и Mini App
- 🔐 **Авторизация** — проверка подписи `initData` от Telegram

---

## ✨ Что умеет приложение

- 👤 **Регистрация** — имя + возрастная группа (выбор плитками)
- 📖 **Учить слова** — карточки со словом, переводом и примером
- 🎯 **Тренировка:**
  - ✅ Выбор перевода из 4 вариантов (мгновенная подсветка)
  - ⌨️ Ввод английского слова с клавиатуры
- 💎 **Баллы** — +10 / −3, защита от ухода в минус
- 📊 **Профиль** — статистика по словам, правильным и ошибкам
- 🌗 **Тема** — автоматически светлая/тёмная под Telegram
- 📳 **Haptic feedback** + **MainButton** + **BackButton** — нативное поведение

---

## 📁 Структура проекта

```
telegram_app/
├── main.py                  # Запускает бота И веб-сервер в одном процессе
├── config.py                # Токен, URL приложения, баллы, возрасты
├── database.py              # SQLite (общая для бота и API)
├── requirements.txt
├── README.md
│
├── handlers/                # Бот
│   ├── __init__.py
│   └── start.py             # /start, /app, /help — кнопка Mini App
│
├── webapp/                  # Mini App
│   ├── __init__.py
│   ├── auth.py              # Проверка initData (HMAC-SHA256)
│   ├── server.py            # aiohttp: статика + JSON API
│   └── static/
│       ├── index.html
│       ├── styles.css       # Темизация под Telegram
│       └── app.js           # Vanilla JS SPA
│
└── data/
    ├── __init__.py
    └── words.py             # Стартовый словарь
```

---

## 🚀 Запуск

### 0. Что нужно

- Python 3.10+
- Токен бота от [@BotFather](https://t.me/BotFather)
- **HTTPS-URL** для Mini App (Telegram открывает только HTTPS)
- Для локальной разработки: [ngrok](https://ngrok.com) или
  [cloudflared](https://github.com/cloudflare/cloudflared)

### 1. Установка зависимостей

```bash
cd telegram_app
python -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Поднимаем HTTPS-туннель к локальному порту 8080

**Вариант A — ngrok** (нужен бесплатный аккаунт + `ngrok config add-authtoken ...`):
```bash
ngrok http 8080
```
В выводе появится строка типа:
```
Forwarding   https://abc123.ngrok-free.app -> http://localhost:8080
```
Это твой `WEBAPP_URL`.

**Вариант B — cloudflared** (без регистрации):
```bash
cloudflared tunnel --url http://localhost:8080
```
В выводе появится `https://something.trycloudflare.com` — твой `WEBAPP_URL`.

### 3. Настраиваем переменные окружения

**Linux / macOS:**
```bash
export BOT_TOKEN="123456789:AAH..."
export WEBAPP_URL="https://abc123.ngrok-free.app"
```

**Windows PowerShell:**
```powershell
$env:BOT_TOKEN="123456789:AAH..."
$env:WEBAPP_URL="https://abc123.ngrok-free.app"
```

(Альтернатива — прописать значения прямо в `config.py`.)

### 4. Регистрируем домен в BotFather (один раз)

Без этого Telegram откажется открывать приложение по твоему URL.

1. Открой [@BotFather](https://t.me/BotFather)
2. `/mybots` → выбери своего бота → **Bot Settings** → **Configure Mini App** → **Enable Mini App**
3. Отправь публичный HTTPS-URL (тот же, что в `WEBAPP_URL`)

> 💡 **Бонус:** там же можно настроить **Menu Button** — постоянную кнопку
> «🚀 Открыть» рядом с полем ввода сообщения. `Bot Settings` →
> `Menu Button` → введи название и URL приложения.

### 5. Запуск

```bash
python main.py
```

В логах увидишь:
```
... | INFO | webapp.server | Mini App сервер слушает http://0.0.0.0:8080
... | INFO | __main__      | ✅ Бот и Mini App запущены.
```

### 6. Проверка

1. Открой бота в Telegram
2. Отправь `/start`
3. Жми «📱 Открыть приложение»
4. Должно открыться полноэкранное окно с регистрацией → меню → обучением

---

## 🤖 Команды бота

| Команда   | Описание                       |
|-----------|--------------------------------|
| `/start`  | Приветствие + кнопка Mini App  |
| `/app`    | Снова показать кнопку          |
| `/help`   | Справка                        |

Всё остальное — внутри приложения.

---

## 🔐 Как работает авторизация

Когда Telegram открывает Mini App, он передаёт в браузер строку
`window.Telegram.WebApp.initData` — querystring вида:
```
user=%7B%22id%22%3A12345%2C...%7D&auth_date=1700000000&hash=...
```

Фронтенд кладёт её в заголовок `X-Telegram-Init-Data` при каждом запросе.
Бэкенд (`webapp/auth.py`) проверяет подпись:
```
secret_key = HMAC_SHA256("WebAppData", BOT_TOKEN)
expected   = HMAC_SHA256(secret_key, sorted_key_value_lines).hexdigest()
```
Если `expected == hash` и `auth_date` свежий — пускаем; иначе 401.
Это значит: подделать запрос без `BOT_TOKEN` невозможно, а сам токен нигде
не уходит на фронт.

---

## 🌐 API эндпоинты

Все, кроме `/`, требуют заголовок `X-Telegram-Init-Data`.

| Метод | Путь                              | Что делает                          |
|-------|-----------------------------------|-------------------------------------|
| GET   | `/`                               | Отдаёт `index.html`                 |
| GET   | `/api/me`                         | Профиль или флаг `registered:false` |
| POST  | `/api/register`                   | `{name, age_group}`                 |
| POST  | `/api/learn/next`                 | Случайное слово (`current_id?`)     |
| POST  | `/api/training/choice/next`       | Слово + 4 варианта                  |
| POST  | `/api/training/choice/answer`     | `{word_id, selected_id}`            |
| POST  | `/api/training/input/next`        | Перевод → ждём слово                |
| POST  | `/api/training/input/answer`      | `{word_id, answer}`                 |

---

## ⚙️ Настройка

Всё в `config.py`:
- `BOT_TOKEN`, `WEBAPP_URL`, `WEBAPP_HOST`, `WEBAPP_PORT`
- `POINTS_CORRECT` / `POINTS_WRONG`
- `AGE_GROUPS`
- `DB_PATH`

Стартовый словарь — в `data/words.py`. Чтобы добавить свои слова,
дополни список **до** первого запуска, либо удали `bot_database.db`
и перезапусти (он перезальётся).

---

## 🧩 Куда развивать

- **Категории слов** — добавь поле `category` в `words`, фильтр в API,
  пикер на фронте
- **Spaced repetition** — поле `last_seen` уже есть, добавь приоритет
  выбора слова в `get_random_word`
- **Озвучка** — храни `audio_file_id`, отдавай через бота
- **Лидерборд** — `SELECT name, points FROM users ORDER BY points DESC`
- **Темы** — Mini App уже подхватывает тему Telegram через CSS-переменные

---

## 📦 Зависимости

- `aiogram==3.13.1` — бот
- `aiohttp==3.10.10` — веб-сервер Mini App
- `aiosqlite==0.20.0` — асинхронный SQLite

---

## 🐛 Частые проблемы

**Кнопка «Открыть приложение» не работает.**
В BotFather не подтверждён HTTPS-домен Mini App (шаг 4).

**Открывается, но «😕 Что-то пошло не так: unauthorized».**
`BOT_TOKEN` в окружении не совпадает с токеном бота, через которого
ты открыл приложение. Проверь, что переменные окружения переданы тому
самому процессу, который ты запустил.

**Открывается, но `Откройте приложение через бота в Telegram`.**
Ты открываешь URL в обычном браузере. Так и должно быть — `initData`
есть только когда Telegram сам открывает страницу.

**ngrok URL меняется при каждом запуске.**
В бесплатном тарифе — да. Запиши новый URL в `WEBAPP_URL` и в BotFather,
либо используй платный статический домен.
