"""Entrypoint: one process serves the Mini App, its API, and runs the bot.

Bot transport is chosen automatically:
- public URL known (any PaaS, or PUBLIC_URL set)  -> Telegram webhook
- otherwise (local dev)                            -> long polling

Run with:  uvicorn app.main:app --host 0.0.0.0 --port 8080
"""
import asyncio
import contextlib
import hashlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from . import bot as botmod
from .api import router as api_router
from .config import settings
from .db import init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tracker")

STATIC_DIR = Path(__file__).parent / "static"
WEBHOOK_PATH = "/tg/webhook"


def _webhook_secret() -> str:
    return hashlib.sha256(settings.bot_token.encode()).hexdigest()[:32]


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    app.state.bot = None
    app.state.dp = None
    polling_task = None

    if settings.bot_configured:
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode

        bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()
        dp.include_router(botmod.router)
        botmod.set_bot(bot)
        app.state.bot = bot
        app.state.dp = dp

        webhook_ok = False
        if settings.public_url:
            try:
                await bot.set_webhook(
                    settings.public_url + WEBHOOK_PATH,
                    secret_token=_webhook_secret(),
                    allowed_updates=dp.resolve_used_update_types(),
                )
                webhook_ok = True
                log.info("Webhook set to %s%s", settings.public_url, WEBHOOK_PATH)
            except Exception:
                log.exception("Could not set webhook; falling back to polling.")

        if not webhook_ok:
            async def poll():
                try:
                    await bot.delete_webhook(drop_pending_updates=False)
                    await dp.start_polling(bot, handle_signals=False)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Bot polling crashed — check BOT_TOKEN. Web app keeps running.")

            polling_task = asyncio.create_task(poll())
            log.info("Bot polling started.")
    else:
        log.warning("BOT_TOKEN not set — running web app only, no bot / no announcements.")

    yield

    if polling_task:
        polling_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await polling_task
    if app.state.bot:
        await app.state.bot.session.close()
    botmod.set_bot(None)


app = FastAPI(title="Community Feature Tracker", lifespan=lifespan)
app.include_router(api_router, prefix="/api")


@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request) -> Response:
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != _webhook_secret():
        return Response(status_code=403)
    bot, dp = app.state.bot, app.state.dp
    if bot is None or dp is None:
        return Response(status_code=503)
    from aiogram.types import Update

    update = Update.model_validate(await request.json())
    await dp.feed_update(bot, update)
    return Response(status_code=200)


app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
