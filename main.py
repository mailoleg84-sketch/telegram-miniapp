"""Точка входа: запускает aiogram polling и aiohttp-сервер Mini App вместе."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, DATABASE_URL
from database import init_db, close_pool
from handlers import start
from webapp.server import run_webapp


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

    await bot.delete_webhook(drop_pending_updates=True)
    runner = await run_webapp()

    logging.info("Бот и Mini App запущены.")
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
