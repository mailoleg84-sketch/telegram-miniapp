from aiohttp import web
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


async def index(request):
    return web.FileResponse(os.path.join(BASE_DIR, "index.html"))


async def run_webapp():
    app = web.Application()

    # ✅ раздача статических файлов (ЭТО КЛЮЧЕВОЕ)
    app.router.add_static("/static/", path=BASE_DIR, name="static")

    # главная страница
    app.router.add_get("/", index)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(app, "0.0.0.0", 10000)
    await site.start()

    return runner
