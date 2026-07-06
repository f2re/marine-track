from __future__ import annotations

import asyncio
import html

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from marine_track.telegram_commands import BOT_COMMAND_LINES
from marine_track.telegram_config import TelegramBotConfig, load_telegram_config
from marine_track.telegram_detection import (
    DETECT_CALLBACK_PREFIX,
    detect_bbox_command as scene_detect_bbox_command,
    detect_callback as scene_detect_callback,
    detect_command as scene_detect_command,
)
from marine_track.telegram_scene_browser import (
    CALLBACK_PREFIX,
    bbox_dates_command as scene_bbox_dates_command,
    image_callback as scene_image_callback,
    image_command as scene_image_command,
    list_dates_command as scene_dates_command,
)

CONFIG: TelegramBotConfig | None = None
JOB_SEMAPHORE: asyncio.Semaphore | None = None

HELP_TEXT = """<b>Marine Track Bot</b>

Команды:
<code>/dates [auto|sentinel1|sentinel2] [hours]</code> — доступные сроки по AOI.
<code>/bboxdates [auto|sentinel1|sentinel2] west south east north [hours]</code> — сроки по bbox.
<code>/image token</code> — preview/quicklook выбранной сцены.
<code>/detect token</code> — детекция по сохраненному scene token.
<code>/detectbbox [auto|sentinel1|sentinel2] west south east north [hours]</code> — найти GeoTIFF/COG сцену и запустить детекцию.
<code>/status</code> — конфигурация.
<code>/whoami</code> — Telegram user id.
"""


def get_config() -> TelegramBotConfig:
    global CONFIG
    if CONFIG is None:
        CONFIG = load_telegram_config()
    return CONFIG


def get_semaphore() -> asyncio.Semaphore:
    global JOB_SEMAPHORE
    if JOB_SEMAPHORE is None:
        JOB_SEMAPHORE = asyncio.Semaphore(get_config().max_concurrent_jobs)
    return JOB_SEMAPHORE


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def is_authorized(update: Update) -> bool:
    config = get_config()
    return not config.admin_ids or effective_user_id(update) in config.admin_ids


async def require_authorized(update: Update) -> bool:
    if is_authorized(update):
        return True
    if update.effective_message:
        await update.effective_message.reply_text(
            f"Доступ закрыт. Ваш Telegram user id: {effective_user_id(update)}."
        )
    return False


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "🚢 Marine Track\n\n"
            "Сроки снимков: /dates или /bboxdates. Детекция: /detect или /detectbbox."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(f"Ваш Telegram user id: {effective_user_id(update)}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    config = get_config()
    lines = [
        "Marine Track Bot",
        f"default_aoi: {config.default_aoi}",
        f"output_dir: {config.output_dir}",
        f"default_sensor: {config.default_sensor.value}",
        f"default_lookback_hours: {config.default_lookback_hours}",
        f"max_results: {config.max_results}",
        f"max_concurrent_jobs: {config.max_concurrent_jobs}",
        f"admin_restricted: {'yes' if config.admin_ids else 'no'}",
        "",
        *BOT_COMMAND_LINES,
    ]
    await update.effective_message.reply_text(
        "<pre>" + html.escape("\n".join(lines)) + "</pre>",
        parse_mode=ParseMode.HTML,
    )


async def dates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_dates_command(update, context, get_config())


async def bboxdates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_bbox_dates_command(update, context, get_config())


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        await scene_image_command(update, context, get_config())


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_detect_command(update, context, get_config())


async def detectbbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_detect_bbox_command(update, context, get_config())


async def image_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        await scene_image_callback(update, context, get_config())


async def detect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_detect_callback(update, context, get_config())


def build_application() -> Application:
    app = Application.builder().token(get_config().token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("whoami", whoami_command))
    app.add_handler(CommandHandler("dates", dates_command))
    app.add_handler(CommandHandler("bboxdates", bboxdates_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("detect", detect_command))
    app.add_handler(CommandHandler("detectbbox", detectbbox_command))
    app.add_handler(CallbackQueryHandler(image_callback, pattern=f"^{CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(detect_callback, pattern=f"^{DETECT_CALLBACK_PREFIX}:"))
    return app


def main() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
