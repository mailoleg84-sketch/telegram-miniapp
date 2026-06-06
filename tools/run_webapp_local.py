"""Локальный запуск ТОЛЬКО веб-сервера Mini App (без бота).

Назначение: дизайн/QA в браузере на localhost без риска для продакшена.
НЕ запускает aiogram polling и НЕ трогает Telegram webhook (в отличие от
main.py), поэтому живой бот на Render продолжает работать.
Пул к Neon создаётся лениво при первом запросе; init_db() с пересидингом
5000 слов здесь намеренно НЕ вызывается — таблицы уже есть в проде.

Запуск:
    .venv\\Scripts\\python.exe -m tools.run_webapp_local
"""
import asyncio
import logging
import sys

from database import close_pool
from webapp.server import run_webapp
from config import WEBAPP_PORT


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    runner = await run_webapp()  # без bot/dispatcher -> только статика + API
    logging.info("Локальный Mini App доступен на http://localhost:%s", WEBAPP_PORT)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await close_pool()


if __name__ == "__main__":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("\nОстановлено.", file=sys.stderr)
