from __future__ import annotations

import html
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from marine_track.telegram_config import TelegramBotConfig

MENU_CALLBACK_PREFIX = "mtmenu"
ACTION_DATES_DEFAULT = "dates_default"
ACTION_DETECT_DEFAULT = "detect_default"
ACTION_DETECT_LAST_BBOX = "detect_last_bbox"
ACTION_DATES_LAST_BBOX = "dates_last_bbox"
ACTION_STATUS = "status"
ACTION_HELP = "help"
ACTION_WHOAMI = "whoami"


def main_menu_markup(has_last_bbox: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🔎 Найти суда", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DETECT_DEFAULT}"),
            InlineKeyboardButton("🕒 Сроки снимков", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DATES_DEFAULT}"),
        ],
    ]
    if has_last_bbox:
        rows.append(
            [
                InlineKeyboardButton("↻ Повторить район", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DETECT_LAST_BBOX}"),
                InlineKeyboardButton("🕒 Сроки района", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DATES_LAST_BBOX}"),
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton("⚙️ Статус", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_STATUS}"),
                InlineKeyboardButton("❓ Помощь", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_HELP}"),
            ],
            [InlineKeyboardButton("🆔 Мой ID", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_WHOAMI}")],
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_menu_markup(has_last_bbox: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_HELP}")]]
    )


def start_text(config: TelegramBotConfig, last_bbox_label: str | None = None) -> str:
    last_bbox = f"\nПоследний район: <code>{html.escape(last_bbox_label)}</code>" if last_bbox_label else ""
    return (
        "<b>Marine Track</b>\n"
        "Поиск спутниковых снимков и первичная детекция судов.\n\n"
        "<b>Быстрый путь</b>\n"
        "1. Нажмите <b>🔎 Найти суда</b>.\n"
        "2. Бот найдет свежий GeoTIFF/COG снимок по default AOI.\n"
        "3. Получите обзор, crop судов и GeoJSON/CSV/Parquet.\n\n"
        f"Default AOI: <code>{html.escape(str(config.default_aoi))}</code>\n"
        f"Период: <code>{config.default_lookback_hours} ч</code>, sensor: <code>{config.default_sensor.value}</code>"
        f"{last_bbox}"
    )


def help_text() -> str:
    return (
        "<b>Как пользоваться</b>\n\n"
        "<b>Без ручного ввода</b>\n"
        "• <b>🔎 Найти суда</b> — поиск свежей сцены по default AOI и запуск детекции.\n"
        "• <b>↻ Повторить район</b> — повторить последний bbox из /detectbbox.\n"
        "• <b>🕒 Сроки района</b> — показать снимки для последнего bbox.\n\n"
        "<b>Команды для точного управления</b>\n"
        "<code>/dates sentinel1 12</code> — сроки по default AOI.\n"
        "<code>/bboxdates sentinel1 36.5 43.8 38.5 45.0 12</code> — сроки по bbox.\n"
        "<code>/detectbbox sentinel1 36.5 43.8 38.5 45.0 12</code> — сразу найти и обработать bbox.\n"
        "<code>/detect token</code> — повторить детекцию по сохраненному token.\n"
        "<code>/image token</code> — preview сцены.\n\n"
        "<b>Формат bbox</b>\n"
        "<code>west south east north</code>, координаты в градусах WGS84."
    )


def status_text(
    config: TelegramBotConfig,
    authorized: bool,
    user_id: int,
    last_bbox_label: str | None = None,
) -> str:
    land_mask = config.land_mask_geojson if config.land_mask_geojson else "off"
    land_mask_exists = path_status(config.land_mask_geojson)
    default_aoi_exists = "ok" if config.default_aoi.is_file() else "missing"
    last_bbox = last_bbox_label or "none"
    return (
        "<b>Статус Marine Track</b>\n"
        f"user_id: <code>{user_id}</code>\n"
        f"access: <code>{'allowed' if authorized else 'denied'}</code>\n"
        f"default_aoi: <code>{html.escape(str(config.default_aoi))}</code> ({default_aoi_exists})\n"
        f"last_bbox: <code>{html.escape(last_bbox)}</code>\n"
        f"sensor: <code>{config.default_sensor.value}</code>\n"
        f"lookback: <code>{config.default_lookback_hours} ч</code>\n"
        f"max_results: <code>{config.max_results}</code>\n"
        f"max_crops: <code>{config.detection_max_crops}</code>\n"
        f"land_mask: <code>{html.escape(str(land_mask))}</code> ({land_mask_exists})\n"
        f"shoreline_buffer_m: <code>{config.shoreline_buffer_m}</code>\n"
        f"output_dir: <code>{html.escape(str(config.output_dir))}</code>"
    )


def path_status(path: Path | None) -> str:
    if path is None:
        return "off"
    return "ok" if path.is_file() else "missing"


def compact_error(title: str, detail: object, next_step: str | None = None) -> str:
    text = f"⚠️ <b>{html.escape(title)}</b>\n<code>{html.escape(str(detail))}</code>"
    if next_step:
        text += f"\n\nЧто сделать: {next_step}"
    return text
