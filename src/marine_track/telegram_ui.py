from __future__ import annotations

import html
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_user_state import (
    OUTPUT_MODE_ALL,
    OUTPUT_MODE_FILES,
    OUTPUT_MODE_IMAGES,
    SavedBbox,
    bbox_label,
    output_mode_label,
)

MENU_CALLBACK_PREFIX = "mtmenu"
AREA_CALLBACK_PREFIX = "mtarea"
OUTPUT_CALLBACK_PREFIX = "mtout"
ACTION_DATES_DEFAULT = "dates_default"
ACTION_DETECT_DEFAULT = "detect_default"
ACTION_DETECT_LAST_BBOX = "detect_last_bbox"
ACTION_DATES_LAST_BBOX = "dates_last_bbox"
ACTION_AREAS = "areas"
ACTION_OUTPUT_MODE = "output_mode"
ACTION_CALIBRATION = "calibration"
ACTION_MENU = "menu"
ACTION_STATUS = "status"
ACTION_HELP = "help"
ACTION_WHOAMI = "whoami"


def main_menu_markup(
    has_last_bbox: bool = False,
    bbox_count: int | None = None,
    is_admin: bool = False,
    calibration_needed: bool = False,
) -> InlineKeyboardMarkup:
    saved_count = bbox_count if bbox_count is not None else int(has_last_bbox)
    rows = [
        [
            InlineKeyboardButton(
                "🔎 Найти кандидаты",
                callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DETECT_DEFAULT}",
            ),
            InlineKeyboardButton(
                "🕒 Сроки снимков",
                callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DATES_DEFAULT}",
            ),
        ],
    ]
    if saved_count == 1:
        rows.append(
            [
                InlineKeyboardButton(
                    "↻ Повторить район",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DETECT_LAST_BBOX}",
                ),
                InlineKeyboardButton(
                    "🕒 Сроки района",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_DATES_LAST_BBOX}",
                ),
            ]
        )
    elif saved_count > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    "📍 Мои районы",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_AREAS}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "📤 Выдача", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_OUTPUT_MODE}"
            ),
            InlineKeyboardButton(
                "⚙️ Статус", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_STATUS}"
            ),
        ]
    )
    if is_admin:
        marker = "⚠️ " if calibration_needed else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{marker}🧪 Калибровка",
                    callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "❓ Помощь", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_HELP}"
            ),
            InlineKeyboardButton(
                "🆔 Мой ID", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_WHOAMI}"
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)


def back_to_menu_markup(has_last_bbox: bool = False) -> InlineKeyboardMarkup:
    del has_last_bbox
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}")]]
    )


def start_text(config: TelegramBotConfig, last_bbox_label: str | None = None) -> str:
    last_bbox = (
        f"\nПоследний район: <code>{html.escape(last_bbox_label)}</code>"
        if last_bbox_label
        else ""
    )
    return (
        "<b>Marine Track</b>\n"
        "Поиск спутниковых снимков и первичная детекция кандидатов судов. "
        "Ranking score не является вероятностью, AIS — внешний reference, Kelvin speed — research proxy.\n\n"
        "<b>Быстрый путь</b>\n"
        "1. Нажмите <b>🔎 Найти кандидаты</b>.\n"
        "2. Бот найдёт свежий GeoTIFF/COG снимок по default AOI.\n"
        "3. Получите обзор кандидатов, crop и GeoJSON/CSV/Parquet.\n\n"
        f"Default AOI: <code>{html.escape(str(config.default_aoi))}</code>\n"
        f"Период: <code>{config.default_lookback_hours} ч</code>, "
        f"sensor: <code>{config.default_sensor.value}</code>{last_bbox}"
    )


def help_text() -> str:
    return (
        "<b>Как пользоваться</b>\n\n"
        "<b>Без ручного ввода</b>\n"
        "• <b>🔎 Найти кандидаты</b> — поиск свежей сцены и candidate detection.\n"
        "• <b>↻ Повторить район</b> — повторить последний bbox из /detectbbox.\n"
        "• <b>🕒 Сроки района</b> — показать снимки для последнего bbox.\n"
        "• <b>📍 Мои районы</b> — выбрать сохранённый bbox.\n"
        "• <b>📤 Выдача</b> — выбрать картинки, файлы или всё.\n\n"
        "<b>Интерпретация</b>\n"
        "• ranking_score — относительный score, не вероятность.\n"
        "• operational speed по умолчанию не оценена.\n"
        "• AIS SOG/COG — внешний reference, не ground truth.\n"
        "• Kelvin speed — экспериментальный research proxy.\n\n"
        "<b>Команды для точного управления</b>\n"
        "<code>/dates sentinel1 12</code> — сроки по default AOI.\n"
        "<code>/bboxdates sentinel1 36.5 43.8 38.5 45.0 12</code> — сроки по bbox.\n"
        "<code>/detectbbox sentinel1 36.5 43.8 38.5 45.0 12</code> — обработать bbox.\n"
        "<code>/areas</code> — список сохранённых районов.\n"
        "<code>/detect token</code> — повторить обработку сохранённой сцены.\n"
        "<code>/image token</code> — preview сцены.\n"
        "<code>/calibrate</code> — интерфейс разметки для администратора.\n\n"
        "<b>Формат bbox</b>\n"
        "<code>west south east north</code>, координаты WGS84."
    )


def status_text(
    config: TelegramBotConfig,
    authorized: bool,
    user_id: int,
    last_bbox_label: str | None = None,
    output_mode: str = OUTPUT_MODE_ALL,
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
        f"output_mode: <code>{html.escape(output_mode_label(output_mode))}</code>\n"
        f"sensor: <code>{config.default_sensor.value}</code>\n"
        f"lookback: <code>{config.default_lookback_hours} ч</code>\n"
        f"max_results: <code>{config.max_results}</code>\n"
        f"max_crops: <code>{config.detection_max_crops}</code>\n"
        f"land_mask: <code>{html.escape(str(land_mask))}</code> ({land_mask_exists})\n"
        f"shoreline_buffer_m: <code>{config.shoreline_buffer_m}</code>\n"
        f"calibration_min_labels: <code>{config.calibration_min_labels}</code>\n"
        "result_type: <code>vessel_candidates</code>\n"
        "operational_speed: <code>not_estimated by default</code>\n"
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


def areas_text(saved_bboxes: list[SavedBbox]) -> str:
    if not saved_bboxes:
        return (
            "<b>Сохранённые районы</b>\n"
            "Пока пусто.\n\n"
            "Что сделать: выполните <code>/bboxdates</code> или <code>/detectbbox</code>."
        )
    lines = ["<b>Сохранённые районы</b>"]
    for index, bbox in enumerate(saved_bboxes, start=1):
        lines.append(
            f"{index}. <code>{html.escape(bbox_label(bbox))}</code> · "
            f"запусков: <code>{bbox.use_count}</code>"
        )
    lines.append("")
    lines.append("Выберите действие под нужным районом.")
    return "\n".join(lines)


def areas_markup(saved_bboxes: list[SavedBbox]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, bbox in enumerate(saved_bboxes, start=1):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index} 🔎 Кандидаты",
                    callback_data=f"{AREA_CALLBACK_PREFIX}:d:{bbox.id}",
                ),
                InlineKeyboardButton(
                    f"{index} 🕒 Сроки", callback_data=f"{AREA_CALLBACK_PREFIX}:t:{bbox.id}"
                ),
                InlineKeyboardButton(
                    f"{index} 🗑", callback_data=f"{AREA_CALLBACK_PREFIX}:x:{bbox.id}"
                ),
            ]
        )
    rows.append(
        [InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}")]
    )
    return InlineKeyboardMarkup(rows)


def output_mode_text(current_mode: str) -> str:
    return (
        "<b>Режим выдачи результата</b>\n"
        f"Сейчас: <code>{html.escape(output_mode_label(current_mode))}</code>\n\n"
        "<b>Картинки</b> — overview и crop кандидатов.\n"
        "<b>Файлы</b> — GeoJSON, CSV, Parquet и report.json.\n"
        "<b>Всё</b> — картинки и файлы."
    )


def output_mode_markup(current_mode: str) -> InlineKeyboardMarkup:
    def button(label: str, mode: str) -> InlineKeyboardButton:
        prefix = "✓ " if mode == current_mode else ""
        return InlineKeyboardButton(
            f"{prefix}{label}", callback_data=f"{OUTPUT_CALLBACK_PREFIX}:{mode}"
        )

    return InlineKeyboardMarkup(
        [
            [button("🖼 Картинки", OUTPUT_MODE_IMAGES), button("📄 Файлы", OUTPUT_MODE_FILES)],
            [button("🧾 Всё", OUTPUT_MODE_ALL)],
            [InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}")],
        ]
    )
