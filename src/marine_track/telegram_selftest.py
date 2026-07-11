from __future__ import annotations

import asyncio
import html
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.provider_canary import CanaryRunResult, run_sentinel1_canary
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX

SELFTEST_CALLBACK_PREFIX = "mtself"
ACTION_OPEN = "open"
ACTION_ASSET = "asset"
ACTION_DETECTION_CONFIRM = "confirm"
ACTION_DETECTION_RUN = "run"
_SELFTEST_LOCK: asyncio.Lock | None = None


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def is_selftest_admin(update: Update, config: TelegramBotConfig) -> bool:
    return effective_user_id(update) in config.admin_ids


def selftest_menu_text() -> str:
    return (
        "🩺 <b>Самопроверка Sentinel-1</b>\n"
        "Проверка запускается только вручную и не расходует provider quota при старте бота.\n\n"
        "<b>Asset canary</b> выполняет компактный AOI → поиск сцены → runtime signing/OAuth → "
        "TIFF range-read. Raster не скачивается целиком.\n\n"
        "<b>Полный тест</b> дополнительно материализует компактный crop и запускает один detection run. "
        "Wake/Kelvin research должен быть выключен."
    )


def selftest_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔌 Проверить provider и asset",
                    callback_data=_callback(ACTION_ASSET),
                )
            ],
            [
                InlineKeyboardButton(
                    "🛰 Полный малый detection test",
                    callback_data=_callback(ACTION_DETECTION_CONFIRM),
                )
            ],
            [
                InlineKeyboardButton(
                    "🏠 Меню",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
                )
            ],
        ]
    )


def detection_confirmation_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Подтвердить полный тест",
                    callback_data=_callback(ACTION_DETECTION_RUN),
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Отмена",
                    callback_data=_callback(ACTION_OPEN),
                )
            ],
        ]
    )


async def selftest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    if not await require_selftest_admin(update, config):
        return
    await show_selftest_menu(update)


async def selftest_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not await require_selftest_admin(update, config):
        return
    parts = query.data.split(":")
    if len(parts) != 2 or parts[0] != SELFTEST_CALLBACK_PREFIX:
        return
    action = parts[1]
    if action == ACTION_OPEN:
        await show_selftest_menu(update)
        return
    if action == ACTION_ASSET:
        await run_selftest(update, config, mode="asset", confirmed=False)
        return
    if action == ACTION_DETECTION_CONFIRM:
        await query.message.reply_text(
            "⚠️ <b>Подтверждение полного теста</b>\n"
            "Будет найден один свежий Sentinel-1 asset, загружен компактный AOI crop и выполнена "
            "детекция. Это использует сеть, provider quota, CPU и место в cache. "
            "Wake/Kelvin research в canary не используется.",
            parse_mode=ParseMode.HTML,
            reply_markup=detection_confirmation_markup(),
        )
        return
    if action == ACTION_DETECTION_RUN:
        await run_selftest(update, config, mode="detection", confirmed=True)
        return
    await query.message.reply_text(
        "Кнопка самопроверки устарела. Откройте /selftest заново.",
        reply_markup=selftest_menu_markup(),
    )


async def show_selftest_menu(update: Update) -> None:
    target = _target(update)
    if target:
        await target.reply_text(
            selftest_menu_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=selftest_menu_markup(),
        )


async def require_selftest_admin(update: Update, config: TelegramBotConfig) -> bool:
    if is_selftest_admin(update, config):
        return True
    target = _target(update)
    if target:
        await target.reply_text(
            "Самопроверка доступна только Telegram-администраторам. "
            f"Ваш user id: {effective_user_id(update)}."
        )
    return False


async def run_selftest(
    update: Update,
    config: TelegramBotConfig,
    *,
    mode: str,
    confirmed: bool,
) -> None:
    target = _target(update)
    if not target:
        return
    lock = _selftest_lock()
    if lock.locked():
        await target.reply_text(
            "Самопроверка уже выполняется. Дождитесь её итогового сообщения.",
            reply_markup=selftest_menu_markup(),
        )
        return

    async with lock:
        status = await target.reply_text("⏳ Самопроверка · подготовка")
        loop = asyncio.get_running_loop()

        def progress(stage: str) -> None:
            asyncio.run_coroutine_threadsafe(
                status.edit_text(f"⏳ Самопроверка · {stage}"),
                loop,
            )

        result = await asyncio.to_thread(
            run_sentinel1_canary,
            output_dir=config.output_dir,
            default_aoi=config.default_aoi,
            mode=mode,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            confirm_detection=confirmed,
            land_mask_geojson=config.land_mask_geojson,
            shoreline_buffer_m=config.shoreline_buffer_m,
            progress_callback=progress,
        )
        await status.edit_text(
            selftest_result_text(result.report),
            parse_mode=ParseMode.HTML,
            reply_markup=selftest_menu_markup(),
        )
        await _send_report(target, result)


def selftest_result_text(report: dict[str, Any]) -> str:
    success = report.get("status") == "success"
    scene = report.get("scene") if isinstance(report.get("scene"), dict) else {}
    asset = report.get("asset") if isinstance(report.get("asset"), dict) else {}
    probe = asset.get("probe") if isinstance(asset.get("probe"), dict) else {}
    detection = report.get("detection") if isinstance(report.get("detection"), dict) else {}
    stages = report.get("stages") if isinstance(report.get("stages"), list) else []
    total_ms = sum(
        int(stage.get("duration_ms") or 0)
        for stage in stages
        if isinstance(stage, dict)
    )
    if success:
        lines = [
            "✅ <b>Самопроверка завершена</b>",
            f"mode: <code>{html.escape(str(report.get('mode')))}</code>",
            f"provider: <code>{html.escape(str(scene.get('provider') or 'unknown'))}</code>",
            f"scene: <code>{html.escape(str(scene.get('product_id') or 'unknown'))}</code>",
            f"range-read: <code>{html.escape(str(probe.get('range_supported')))}</code>",
            f"время этапов: <code>{total_ms} ms</code>",
        ]
        if detection:
            lines.extend(
                [
                    f"candidates: <code>{int(detection.get('candidate_count') or 0)}</code>",
                    "wake research: <code>off</code>",
                ]
            )
        return "\n".join(lines)

    error = report.get("error") if isinstance(report.get("error"), dict) else {}
    failed_stage = next(
        (
            str(stage.get("name"))
            for stage in reversed(stages)
            if isinstance(stage, dict) and stage.get("status") == "failed"
        ),
        "configuration",
    )
    return (
        "⛔ <b>Самопроверка не пройдена</b>\n"
        f"этап: <code>{html.escape(failed_stage)}</code>\n"
        f"тип: <code>{html.escape(str(error.get('type') or 'unknown'))}</code>\n"
        f"причина: <code>{html.escape(str(error.get('message') or 'unknown'))}</code>"
    )


async def _send_report(target: Any, result: CanaryRunResult) -> None:
    if not result.report_path.is_file():
        return
    with result.report_path.open("rb") as file_obj:
        await target.reply_document(
            document=file_obj,
            filename="marine-track-selftest.json",
            caption="Redacted self-test report",
        )


def _callback(action: str) -> str:
    return f"{SELFTEST_CALLBACK_PREFIX}:{action}"


def _target(update: Update):
    return update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )


def _selftest_lock() -> asyncio.Lock:
    global _SELFTEST_LOCK
    if _SELFTEST_LOCK is None:
        _SELFTEST_LOCK = asyncio.Lock()
    return _SELFTEST_LOCK
