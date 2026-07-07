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
    PAGE_CALLBACK_PREFIX,
    bbox_dates_command as scene_bbox_dates_command,
    image_callback as scene_image_callback,
    image_command as scene_image_command,
    list_dates_command as scene_dates_command,
    scene_page_callback as scene_scene_page_callback,
)
from marine_track.telegram_ui import (
    ACTION_AREAS,
    ACTION_DATES_DEFAULT,
    ACTION_DATES_LAST_BBOX,
    ACTION_DETECT_DEFAULT,
    ACTION_DETECT_LAST_BBOX,
    ACTION_HELP,
    ACTION_MENU,
    ACTION_OUTPUT_MODE,
    ACTION_STATUS,
    ACTION_WHOAMI,
    AREA_CALLBACK_PREFIX,
    MENU_CALLBACK_PREFIX,
    OUTPUT_CALLBACK_PREFIX,
    areas_markup,
    areas_text,
    help_text,
    main_menu_markup,
    output_mode_markup,
    output_mode_text,
    start_text,
    status_text,
)
from marine_track.telegram_user_state import (
    bbox_command_args,
    bbox_label,
    delete_saved_bbox,
    get_last_bbox,
    get_output_mode,
    get_saved_bbox,
    get_saved_bboxes,
    output_mode_label,
    set_output_mode,
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


def user_output_mode(update: Update) -> str:
    return get_output_mode(get_config().output_dir, effective_user_id(update))


def saved_bbox_count(update: Update) -> int:
    return len(get_saved_bboxes(get_config().output_dir, effective_user_id(update)))


def user_menu_markup(update: Update):
    count = saved_bbox_count(update)
    return main_menu_markup(has_last_bbox=count > 0, bbox_count=count)


def saved_bbox_menu(update: Update):
    saved = get_saved_bboxes(get_config().output_dir, effective_user_id(update))
    return areas_text(saved), areas_markup(saved)


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
            status_text(
                get_config(),
                is_authorized(update),
                effective_user_id(update),
                last_bbox_label(update),
                user_output_mode(update),
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )


async def areas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    if update.effective_message:
        text, markup = saved_bbox_menu(update)
        await update.effective_message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def output_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    if update.effective_message:
        mode = user_output_mode(update)
        await update.effective_message.reply_text(
            output_mode_text(mode),
            parse_mode=ParseMode.HTML,
            reply_markup=output_mode_markup(mode),
        )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    _, _, action = query.data.partition(":")
    if action == ACTION_MENU:
        await query.message.reply_text(
            start_text(get_config(), last_bbox_label(update)),
            parse_mode=ParseMode.HTML,
            reply_markup=user_menu_markup(update),
        )
        return
    if action == ACTION_HELP:
        await query.message.reply_text(help_text(), parse_mode=ParseMode.HTML, reply_markup=user_menu_markup(update))
        return
    if action == ACTION_STATUS:
        await query.message.reply_text(
            status_text(
                get_config(),
                is_authorized(update),
                effective_user_id(update),
                last_bbox_label(update),
                user_output_mode(update),
            ),
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
    if action == ACTION_OUTPUT_MODE:
        if not await require_authorized(update):
            return
        mode = user_output_mode(update)
        await query.message.reply_text(
            output_mode_text(mode),
            parse_mode=ParseMode.HTML,
            reply_markup=output_mode_markup(mode),
        )
        return
    if action == ACTION_AREAS:
        if not await require_authorized(update):
            return
        text, markup = saved_bbox_menu(update)
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
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


async def output_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not await require_authorized(update):
        return
    _, _, mode = query.data.partition(":")
    saved = set_output_mode(get_config().output_dir, effective_user_id(update), mode)
    await query.message.reply_text(
        f"Режим выдачи: <code>{output_mode_label(saved)}</code>",
        parse_mode=ParseMode.HTML,
        reply_markup=output_mode_markup(saved),
    )


async def area_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != AREA_CALLBACK_PREFIX:
        return
    if not await require_authorized(update):
        return

    action, bbox_id = parts[1], parts[2]
    bbox = get_saved_bbox(get_config().output_dir, effective_user_id(update), bbox_id)
    if action == "x":
        deleted = delete_saved_bbox(get_config().output_dir, effective_user_id(update), bbox_id)
        if not deleted:
            await query.message.reply_text(
                "Район уже не найден. Что сделать: откройте /areas заново.",
                reply_markup=user_menu_markup(update),
            )
            return
        text, markup = saved_bbox_menu(update)
        await query.message.reply_text("🗑 Район удален.", reply_markup=user_menu_markup(update))
        await query.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        return
    if bbox is None:
        await query.message.reply_text(
            "Район не найден. Что сделать: откройте /areas или сохраните bbox через /bboxdates.",
            reply_markup=user_menu_markup(update),
        )
        return

    context.args = bbox_command_args(bbox)
    async with get_semaphore():
        if action == "t":
            await scene_bbox_dates_command(update, context, get_config())
        elif action == "d":
            await scene_detect_bbox_command(update, context, get_config())
        else:
            await query.message.reply_text(
                "Неизвестное действие. Что сделать: откройте /areas заново.",
                reply_markup=user_menu_markup(update),
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
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("whoami", whoami_command))
    app.add_handler(CommandHandler("areas", areas_command))
    app.add_handler(CommandHandler("output", output_command))
    app.add_handler(CommandHandler("dates", dates_command))
    app.add_handler(CommandHandler("bboxdates", bboxdates_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("detect", detect_command))
    app.add_handler(CommandHandler("detectbbox", detectbbox_command))
    app.add_handler(CallbackQueryHandler(menu_callback, pattern=f"^{MENU_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(output_callback, pattern=f"^{OUTPUT_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(area_callback, pattern=f"^{AREA_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(scene_scene_page_callback, pattern=f"^{PAGE_CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(image_callback, pattern=f"^{CALLBACK_PREFIX}:"))
    app.add_handler(CallbackQueryHandler(detect_callback, pattern=f"^{DETECT_CALLBACK_PREFIX}:"))
    return app


def main() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
