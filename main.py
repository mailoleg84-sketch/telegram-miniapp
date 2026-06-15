"""Точка входа: запускает aiogram polling и aiohttp-сервер Mini App вместе."""
import asyncio
import logging
import sys
from urllib.parse import urlsplit, urlunsplit

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import (
    BOT_RUN_MODE,
    BOT_TOKEN,
    DATABASE_URL,
    TELEGRAM_WEBHOOK_SECRET,
    WEBAPP_URL,
    WEBHOOK_PATH,
)
from database import init_db, close_pool
from handlers import start
from webapp.server import run_webapp


def _webhook_url() -> str:
    parts = urlsplit(WEBAPP_URL)
    base_path = parts.path.rstrip("/")
    hook_path = "/" + WEBHOOK_PATH.strip("/")
    return urlunsplit((parts.scheme, parts.netloc, base_path + hook_path, "", ""))


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("BOT_TOKEN не задан.", file=sys.stderr)
        sys.exit(1)
    if not DATABASE_URL:
        print("DATABASE_URL не задан (строка подключения Neon).", file=sys.stderr)
        sys.exit(1)

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(start.router)

    mode = BOT_RUN_MODE.lower()
    if mode not in {"polling", "webhook"}:
        mode = "webhook"

    if mode == "webhook":
        if not TELEGRAM_WEBHOOK_SECRET:
            print(
                "TELEGRAM_WEBHOOK_SECRET не задан, а режим webhook требует секрет: "
                "без него любой может слать поддельные апдейты на webhook. "
                "Задайте TELEGRAM_WEBHOOK_SECRET в окружении.",
                file=sys.stderr,
            )
            sys.exit(1)
        runner = await run_webapp(
            bot=bot,
            dispatcher=dp,
            webhook_path=WEBHOOK_PATH,
            webhook_secret=TELEGRAM_WEBHOOK_SECRET,
        )
        webhook_url = _webhook_url()
        await bot.set_webhook(
            webhook_url,
            allowed_updates=dp.resolve_used_update_types(),
            drop_pending_updates=False,
            secret_token=TELEGRAM_WEBHOOK_SECRET or None,
        )
        logging.info("Бот и Mini App запущены в webhook-режиме: %s", webhook_url)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            await bot.session.close()
            await close_pool()
        return

    await bot.delete_webhook(drop_pending_updates=True)
    runner = await run_webapp(bot=bot)  # bot нужен в app['bot'] для рассылки напоминаний
    logging.info("Бот и Mini App запущены в polling-режиме.")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        await close_pool()


if __name__ == "__main__":
    # Фикс WinError 121 на Windows + VPN: используем SelectorEventLoop.
    # На Linux (Render) эта политика недоступна — поэтому в try/except.
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nОстановлено.")
