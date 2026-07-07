from __future__ import annotations

import asyncio

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from marine_track.telegram_config import TelegramBotConfig, load_telegram_config
from marine_track.telegram_detection import (
    DETECT_CALLBACK_PREFIX,
    detect_bbox_command as scene_detect_bbox_command,
    detect_callback as scene_detect_callback,
    detect_command as scene_detect_command,
    detect_default_aoi as scene_detect_default_aoi,
)
from marine_track.telegram_scene_browser import (
    CALLBACK_PREFIX,
    bbox_dates_command as scene_bbox_dates_command,
    image_callback as scene_image_callback,
    image_command as scene_image_command,
    list_dates_command as scene_dates_command,
    parse_scene_hours,
    parse_scene_sensor,
)
from marine_track.telegram_ui import (
    ACTION_DATES_DEFAULT,
    ACTION_DATES_LAST_BBOX,
    ACTION_DETECT_DEFAULT,
    ACTION_DETECT_LAST_BBOX,
    ACTION_HELP,
    ACTION_STATUS,
    ACTION_WHOAMI,
    MENU_CALLBACK_PREFIX,
    help_text,
    main_menu_markup,
    start_text,
    status_text,
)
from marine_track.telegram_user_state import (
    bbox_command_args,
    bbox_label,
    get_last_bbox,
    save_last_bbox,
)

CONFIG: TelegramBotConfig | None = None
JOB_SEMAPHORE: asyncio.Semaphore | None = None


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


def last_bbox_label(update: Update) -> str | None:
    bbox = get_last_bbox(get_config().output_dir, effective_user_id(update))
    return bbox_label(bbox) if bbox else None


def user_menu_markup(update: Update):
    return main_menu_markup(has_last_bbox=last_bbox_label(update) is not None)


def is_authorized(update: Update) -> bool:
    config = get_config()
    return not config.admin_ids or effective_user_id(update) in config.admin_ids


async def require_authorized(update: Update) -> bool:
    if is_authorized(update):
        return True
    target = update.effective_message or (update.callback_query.message if update.callback_query else None)
    if target:
        await target.reply_text(
            f"Доступ закрыт. Ваш Telegram user id: {effective_user_id(update)}.",
            reply_markup=user_menu_markup(update),
        )
    return False


def remember_bbox_args(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = list(context.args or [])
    if len(args) < 5:
        return
    try:
        sensor = parse_scene_sensor(args[0], get_config().default_sensor)
        west, south, east, north = [float(value) for value in args[1:5]]
        hours = parse_scene_hours(args[5] if len(args) > 5 else None)
    except ValueError:
        return
    save_last_bbox(
        get_config().output_dir,
        effective_user_id(update),
        sensor,
        west,
        south,
        east,
        north,
        hours,
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            start_text(get_config(), last_bbox_label(update)),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            help_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start_command(update, context)


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            f"Ваш Telegram user id: <code>{effective_user_id(update)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            status_text(get_config(), is_authorized(update), effective_user_id(update), last_bbox_label(update)),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    _, _, action = query.data.partition(":")
    if action == ACTION_HELP:
        await query.message.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=user_menu_markup(update))
        return
    if action == ACTION_STATUS:
        await query.message.reply_text(
            status_text(get_config(), is_authorized(update), effective_user_id(update), last_bbox_label(update)),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )
        return
    if action == ACTION_WHOAMI:
        await query.message.reply_text(
            f"Ваш Telegram user id: <code>{effective_user_id(update)}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )
        return
    if not await require_authorized(update):
        return
    if action == ACTION_DATES_DEFAULT:
        async with get_semaphore():
            await scene_dates_command(update, context, get_config())
        return
    if action == ACTION_DETECT_DEFAULT:
        async with get_semaphore():
            await scene_detect_default_aoi(update, context, get_config())
        return
    if action in {ACTION_DATES_LAST_BBOX, ACTION_DETECT_LAST_BBOX}:
        bbox = get_last_bbox(get_config().output_dir, effective_user_id(update))
        if bbox is None:
            await query.message.reply_text(
                "Последний bbox не сохранен. Сначала выполните /detectbbox или /bboxdates.",
                reply_markup=user_menu_markup(update),
            )
            return
        context.args = bbox_command_args(bbox)
        async with get_semaphore():
            if action == ACTION_DATES_LAST_BBOX:
                await scene_bbox_dates_command(update, context, get_config())
            else:
                await scene_detect_bbox_command(update, context, get_config())
        return


async def dates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        async with get_semaphore():
            await scene_dates_command(update, context, get_config())


async def bboxdates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_authorized(update):
        remember_bbox_args(update, context)
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
        remember_bbox_args(update, context)
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
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("whoami", whoami_command))
    app.add_handler(CommandHandler("dates", dates_command))
    app.add_handler(CommandHandler("bboxdates", bboxdates_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("detect", detect_command))
    app.add_handler(CommandHandler("detectbbox", detectbbox_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=f"^{MENU_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(image_callback, pattern=f"^{CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(detect_callback, pattern=f"^{DETECT_CALLBACK_PREFIX}:"))
    return app


def main() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
