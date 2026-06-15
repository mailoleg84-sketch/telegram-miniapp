"""Ежедневные напоминания ботом (opt-in).

Триггерится внешним планировщиком (GitHub Actions cron) через защищённый
эндпоинт POST /internal/send-reminders (см. webapp/server.py). Внутрипроцессного
цикла нет специально: на Render free сервис засыпает, а cron-пинг и будит его,
и запускает рассылку. Подробнее — Claude/06 Журнал изменений.

Зависимости направлены «вниз» (config, database). Модуль НЕ импортирует server.py.
"""
import asyncio
import hmac
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import database
from config import (
    APP_VERSION,
    REMINDER_ACTIVITY_WINDOW_DAYS,
    REMINDER_CRON_SECRET,
    WEBAPP_URL,
)

log = logging.getLogger(__name__)

# ~20 сообщений/сек — с запасом под лимит Telegram (30/сек глобально, 1/сек на чат).
_SEND_DELAY_SEC = 0.05


def is_configured() -> bool:
    """True, если задан секрет cron (иначе рассылка выключена, fail-closed)."""
    return bool((REMINDER_CRON_SECRET or "").strip())


def cron_secret_ok(provided: str) -> bool:
    """Сверка секрета из заголовка X-Cron-Secret. Пустой секрет в конфиге →
    всегда False (никаких рассылок, пока владелец не задал секрет)."""
    secret = (REMINDER_CRON_SECRET or "").strip()
    if not secret:
        return False
    return hmac.compare_digest((provided or "").strip(), secret)


def build_reminder_text(name: str, current_streak: int) -> str:
    """Тёплый текст напоминания. Со стриком (≥2 дней) — мотивируем не терять
    серию; иначе мягкое приглашение. Без шейминга и соревнований."""
    who = (name or "").strip()
    if current_streak >= 2:
        lead = f"🔥 {who}, у" if who else "🔥 У"
        return (
            f"{lead} тебя серия {current_streak} дн. подряд! "
            f"Не теряй её — позанимайся английским сегодня 💪"
        )
    lead = f"👋 Привет, {who}!" if who else "👋 Привет!"
    return f"{lead} Сегодня ещё не было английского. Заглянем на пару минут? Тебя ждут новые слова 🎈"


def _webapp_url() -> str:
    parts = urlsplit(WEBAPP_URL)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["v"] = APP_VERSION
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _reminder_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=_webapp_url())),
    ]])


async def send_daily_reminders(bot) -> dict:
    """Разослать напоминания всем подходящим пользователям. Идемпотентно по дням
    (last_reminded_at): повторный вызов в тот же день никого не зацепит. Ошибки
    отдельных отправок не валят цикл; заблокировавших бота — авто-выключаем."""
    if bot is None:
        log.error("send_daily_reminders: экземпляр бота недоступен")
        return {"candidates": 0, "sent": 0, "disabled": 0, "errors": 0, "error": "bot unavailable"}

    try:
        candidates = await database.get_reminder_candidates(REMINDER_ACTIVITY_WINDOW_DAYS)
    except Exception:
        log.exception("get_reminder_candidates упал")
        return {"candidates": 0, "sent": 0, "disabled": 0, "errors": 0, "error": "db error"}

    keyboard = _reminder_keyboard()
    sent = disabled = errors = 0
    for row in candidates:
        user_id = row["user_id"]
        name = row["name"] or ""
        try:
            streak = await database.get_learning_streak(user_id)
            text = build_reminder_text(name, int(streak.get("current_streak", 0)))
            await bot.send_message(user_id, text, reply_markup=keyboard)
            await database.set_reminder_sent(user_id)
            sent += 1
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — это окончательно: выключаем, чтобы
            # не долбить впустую (можно снова включить в Настройках).
            try:
                await database.set_reminders_enabled(user_id, False)
            except Exception:
                log.exception("Не удалось выключить напоминания для %s", user_id)
            disabled += 1
        except TelegramBadRequest:
            # Может быть временной (chat not found и т.п.) — НЕ выключаем навсегда,
            # просто считаем ошибкой и попробуем в следующий раз.
            log.warning("TelegramBadRequest при напоминании user_id=%s", user_id)
            errors += 1
        except Exception:
            log.exception("Ошибка отправки напоминания user_id=%s", user_id)
            errors += 1
        await asyncio.sleep(_SEND_DELAY_SEC)

    log.info(
        "Напоминания: кандидатов=%d, отправлено=%d, выключено=%d, ошибок=%d",
        len(candidates), sent, disabled, errors,
    )
    return {"candidates": len(candidates), "sent": sent, "disabled": disabled, "errors": errors}
