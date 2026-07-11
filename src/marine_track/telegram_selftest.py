from __future__ import annotations

import asyncio
import html
from pathlib import Path
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.provider_canary import (
    CanaryMode,
    load_latest_canary_report,
    run_provider_canary,
)
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX

SELFTEST_CALLBACK_PREFIX = "mtself"
ACTION_OPEN = "open"
ACTION_ASSET = "asset"
ACTION_CONFIRM_DETECTION = "confirm"
ACTION_RUN_DETECTION = "detect"
ACTION_LAST = "last"


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def is_selftest_admin(update: Update, config: TelegramBotConfig) -> bool:
    return effective_user_id(update) in config.admin_ids


async def selftest_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    if not await require_selftest_admin(update, config):
        return
    args = [str(value).strip().lower() for value in (context.args or []) if str(value).strip()]
    if not args:
        await show_selftest_menu(update)
        return
    if args[0] == CanaryMode.ASSET.value:
        await run_selftest(update, config, CanaryMode.ASSET)
        return
    if args[0] == CanaryMode.DETECTION.value:
        await show_detection_confirmation(update)
        return
    if args[0] == ACTION_LAST:
        await show_latest_report(update, config)
        return
    target = _target(update)
    if target:
        await target.reply_text(
            "Формат: <code>/selftest [asset|detection|last]</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=selftest_menu_markup(),
        )


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
    elif action == ACTION_ASSET:
        await run_selftest(update, config, CanaryMode.ASSET)
    elif action == ACTION_CONFIRM_DETECTION:
        await show_detection_confirmation(update)
    elif action == ACTION_RUN_DETECTION:
        await run_selftest(update, config, CanaryMode.DETECTION)
    elif action == ACTION_LAST:
        await show_latest_report(update, config)
    else:
        await query.message.reply_text(
            "Кнопка self-test устарела. Откройте /selftest заново.",
            reply_markup=selftest_menu_markup(),
        )


async def require_selftest_admin(update: Update, config: TelegramBotConfig) -> bool:
    if is_selftest_admin(update, config):
        return True
    target = _target(update)
    if target:
        await target.reply_text(
            "Self-test доступен только Telegram-администраторам. "
            f"Ваш user id: {effective_user_id(update)}."
        )
    return False


async def show_selftest_menu(update: Update) -> None:
    target = _target(update)
    if target:
        await target.reply_text(
            selftest_menu_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=selftest_menu_markup(),
        )


async def show_detection_confirmation(update: Update) -> None:
    target = _target(update)
    if target:
        await target.reply_text(
            detection_confirmation_text(),
            parse_mode=ParseMode.HTML,
            reply_markup=detection_confirmation_markup(),
        )


async def show_latest_report(update: Update, config: TelegramBotConfig) -> None:
    target = _target(update)
    if not target:
        return
    report = load_latest_canary_report(config.output_dir)
    if report is None:
        await target.reply_text(
            "Сохранённого self-test отчёта пока нет.",
            reply_markup=selftest_menu_markup(),
        )
        return
    await target.reply_text(
        format_canary_report(report),
        parse_mode=ParseMode.HTML,
        reply_markup=selftest_result_markup(str(report.get("mode") or "asset")),
    )


async def run_selftest(
    update: Update,
    config: TelegramBotConfig,
    mode: CanaryMode,
) -> None:
    target = _target(update)
    if not target:
        return
    status = await target.reply_text(
        "⏳ Запускаю Sentinel-1 self-test\n"
        f"режим: {mode.value}\n"
        "Проверка выполняется только по явной команде администратора."
    )
    result = await asyncio.to_thread(
        run_provider_canary,
        mode=mode,
        output_dir=config.output_dir,
        default_aoi=config.default_aoi,
        base_dir=Path.cwd(),
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
        land_mask_geojson=config.land_mask_geojson,
        shoreline_buffer_m=config.shoreline_buffer_m,
    )
    await status.edit_text(
        format_canary_report(result.report),
        parse_mode=ParseMode.HTML,
        reply_markup=selftest_result_markup(mode.value),
    )
    try:
        with result.report_path.open("rb") as file_obj:
            await target.reply_document(
                document=file_obj,
                filename=f"marine-track-selftest-{result.report['canary_id']}.json",
                caption="Redacted Sentinel-1 self-test report",
            )
    except OSError:
        pass


def selftest_menu_text() -> str:
    return (
        "🩺 <b>Sentinel-1 operational self-test</b>\n"
        "Проверка не запускается автоматически и расходует provider quota только после нажатия кнопки.\n\n"
        "<b>Asset canary</b> — компактный AOI, live provider search, выбор typed asset, "
        "runtime signing/OAuth и TIFF range-read. Raster целиком не скачивается.\n\n"
        "<b>Detection canary</b> — после отдельного подтверждения дополнительно материализует "
        "компактный crop и запускает operational CFAR. Wake/Kelvin research принудительно выключен."
    )


def selftest_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔍 Проверить provider и asset",
                    callback_data=_callback(ACTION_ASSET),
                )
            ],
            [
                InlineKeyboardButton(
                    "⚠️ Полный detection self-test",
                    callback_data=_callback(ACTION_CONFIRM_DETECTION),
                )
            ],
            [
                InlineKeyboardButton(
                    "📄 Последний отчёт",
                    callback_data=_callback(ACTION_LAST),
                ),
                InlineKeyboardButton(
                    "🏠 Меню",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
                ),
            ],
        ]
    )


def detection_confirmation_text() -> str:
    return (
        "⚠️ <b>Подтвердите detection self-test</b>\n"
        "Будет выполнен live Sentinel-1 search, range-read, загрузка/обрезка одного компактного "
        "raster asset и CFAR detection. Это использует сеть, provider quota, CPU и дисковый кэш.\n\n"
        "Wake/Kelvin research будет принудительно отключён. Результат не считается научной "
        "валидацией точности детектора."
    )


def detection_confirmation_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Запустить detection canary",
                    callback_data=_callback(ACTION_RUN_DETECTION),
                )
            ],
            [
                InlineKeyboardButton(
                    "Отмена",
                    callback_data=_callback(ACTION_OPEN),
                )
            ],
        ]
    )


def selftest_result_markup(mode: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                "↻ Asset canary",
                callback_data=_callback(ACTION_ASSET),
            )
        ]
    ]
    if mode != CanaryMode.DETECTION.value:
        rows.append(
            [
                InlineKeyboardButton(
                    "⚠️ Detection canary",
                    callback_data=_callback(ACTION_CONFIRM_DETECTION),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("🩺 Self-test", callback_data=_callback(ACTION_OPEN)),
            InlineKeyboardButton(
                "🏠 Меню",
                callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}",
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def format_canary_report(report: dict[str, Any]) -> str:
    passed = report.get("status") == "passed"
    icon = "✅" if passed else "⛔"
    result = report.get("result") if isinstance(report.get("result"), dict) else {}
    search = result.get("search") if isinstance(result.get("search"), dict) else {}
    asset = result.get("asset") if isinstance(result.get("asset"), dict) else {}
    probe = asset.get("probe") if isinstance(asset.get("probe"), dict) else {}
    detection = result.get("detection") if isinstance(result.get("detection"), dict) else {}
    aoi = report.get("aoi") if isinstance(report.get("aoi"), dict) else {}

    lines = [
        f"{icon} <b>Sentinel-1 self-test: {html.escape(str(report.get('status') or 'unknown'))}</b>",
        f"mode: <code>{html.escape(str(report.get('mode') or 'unknown'))}</code> · "
        f"duration: <code>{int(report.get('duration_ms') or 0)} ms</code>",
        f"AOI: <code>{html.escape(str(aoi.get('source') or 'unknown'))}</code> · "
        f"<code>{float(aoi.get('area_km2') or 0.0):.1f} km²</code>",
    ]
    if search:
        lines.extend(
            [
                f"provider: <code>{html.escape(str(search.get('provider') or 'unknown'))}</code> · "
                f"scenes: <code>{int(search.get('scene_count') or 0)}</code>",
                f"scene time: <code>{html.escape(str(search.get('acquisition_time') or 'unknown'))}</code>",
            ]
        )
    if asset:
        lines.append(
            f"asset: <code>{html.escape(str(asset.get('key') or 'unknown'))}</code> · "
            f"access: <code>{html.escape(str(asset.get('access_mode') or 'unknown'))}</code>"
        )
        lines.append(
            f"probe: HTTP <code>{html.escape(str(probe.get('status') or 'local'))}</code> · "
            f"range: <code>{html.escape(str(probe.get('range_supported')))}</code> · "
            f"bytes: <code>{int(probe.get('bytes_checked') or 0)}</code>"
        )
    if detection:
        lines.extend(
            [
                f"candidates: <code>{int(detection.get('candidate_count') or 0)}</code> · "
                f"crop: <code>{html.escape(str(detection.get('aoi_cropped')))}</code>",
                f"preprocessing: <code>{html.escape(str(detection.get('preprocessing_domain') or 'unknown'))}</code> · "
                f"calibration: <code>{html.escape(str(detection.get('calibration_status') or 'unknown'))}</code>",
                "wake research: <code>disabled</code>",
            ]
        )

    stages = report.get("stages") if isinstance(report.get("stages"), list) else []
    if stages:
        lines.append("")
        lines.append("<b>Stages</b>")
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            marker = "✓" if stage.get("status") == "passed" else "✗"
            lines.append(
                f"{marker} <code>{html.escape(str(stage.get('name') or 'unknown'))}</code> "
                f"{int(stage.get('duration_ms') or 0)} ms"
            )

    error = report.get("error") if isinstance(report.get("error"), dict) else None
    if error:
        lines.extend(
            [
                "",
                "<b>Ошибка</b>",
                f"<code>{html.escape(str(error.get('type') or 'Error'))}: "
                f"{html.escape(str(error.get('message') or 'unknown'))}</code>",
            ]
        )
    lines.append("")
    lines.append("Отчёт redacted: credentials, query signatures и абсолютные пути не сохраняются.")
    return "\n".join(lines)


def _callback(action: str) -> str:
    return f"{SELFTEST_CALLBACK_PREFIX}:{action}"


def _target(update: Update):
    return update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )
