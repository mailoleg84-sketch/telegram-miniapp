"""Точка входа: запускает aiogram polling и aiohttp-сервер Mini App вместе."""
from ai_tutor import ask_ai
from user_service import get_user, add_xp
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, WEBAPP_URL
from database import init_db
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


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
from ai_tutor import ask_ai

@dp.message()
async def handle_message(message: types.Message):
    text = message.text

    reply = ask_ai(text)

    await message.answer(reply)
from database import init_db

@app.on_event("startup")
async def startup():
    await init_db()
