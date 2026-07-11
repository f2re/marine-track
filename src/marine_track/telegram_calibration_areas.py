from __future__ import annotations

import asyncio
import html
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.calibration_area_pipeline import (
    load_search_session,
    prepare_calibration_data,
    search_calibration_scenes,
    session_tokens,
)
from marine_track.calibration_areas import (
    AREA_GROUPS,
    CALIBRATION_AREAS,
    CalibrationArea,
    areas_for_group,
    get_area_group,
    get_calibration_area,
    paginate_areas,
)
from marine_track.models import Sensor
from marine_track.sensor_preprocessing import sentinel2_single_band_enabled
from marine_track.telegram_calibration_phase2 import context_geojson, phase2_targets
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_scene_browser import bbox_geojson, read_geojson
from marine_track.telegram_user_state import SavedBbox, get_saved_bbox, get_saved_bboxes

CALLBACK_PREFIX = "mtcal"
ACTION_AREA_HOME = "ahome"
ACTION_AREA_GROUP = "agroup"
ACTION_AREA_ALL = "aall"
ACTION_AREA_SELECT = "aselect"
ACTION_AREA_SAVED = "asaved"
ACTION_AREA_SENSOR = "asensor"
ACTION_AREA_SEARCH = "asearch"
ACTION_AREA_RUN = "arun"
ACTION_AREA_BATCH = "abatch"
ACTION_AREA_S2_INFO = "as2info"
CALIBRATION_AREA_ACTIONS = {
    ACTION_AREA_HOME,
    ACTION_AREA_GROUP,
    ACTION_AREA_ALL,
    ACTION_AREA_SELECT,
    ACTION_AREA_SAVED,
    ACTION_AREA_SENSOR,
    ACTION_AREA_SEARCH,
    ACTION_AREA_RUN,
    ACTION_AREA_BATCH,
    ACTION_AREA_S2_INFO,
}
SENSOR_CODES = {"s1": Sensor.SENTINEL1, "s2": Sensor.SENTINEL2, "auto": Sensor.AUTO}
PERIODS = (24, 72, 168, 336, 720)


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


async def calibration_area_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    if not _is_admin(update, config):
        await query.message.reply_text("Калибровочные акватории доступны только администраторам.")
        return
    parts = query.data.split(":")
    if len(parts) < 2 or parts[0] != CALLBACK_PREFIX:
        return
    action = parts[1]

    if action == ACTION_AREA_HOME:
        await show_area_home(update, config)
        return
    if action == ACTION_AREA_GROUP and len(parts) == 4:
        await show_group_page(update, config, parts[2], _page(parts[3]))
        return
    if action == ACTION_AREA_ALL and len(parts) == 3:
        await show_all_page(update, config, _page(parts[2]))
        return
    if action == ACTION_AREA_SAVED:
        await show_saved_areas(update, config)
        return
    if action == ACTION_AREA_SELECT and len(parts) == 3:
        await show_area_sensor_choice(update, config, parts[2])
        return
    if action == ACTION_AREA_SENSOR and len(parts) == 4:
        await show_period_choice(update, config, parts[2], parts[3])
        return
    if action == ACTION_AREA_S2_INFO and len(parts) == 3:
        await show_sentinel2_not_ready(update, parts[2])
        return
    if action == ACTION_AREA_SEARCH and len(parts) == 5:
        await search_area(update, config, parts[2], parts[3], _hours(parts[4]))
        return
    if action == ACTION_AREA_RUN and len(parts) == 3:
        await prepare_tokens(update, config, [parts[2]])
        return
    if action == ACTION_AREA_BATCH and len(parts) == 4:
        await prepare_session(update, config, parts[2], _batch_limit(parts[3]))
        return
    await query.message.reply_text(
        "Кнопка устарела или повреждена. Откройте выбор акватории заново.",
        reply_markup=area_home_markup(config, effective_user_id(update)),
    )


async def show_area_home(update: Update, config: TelegramBotConfig) -> None:
    target = _target(update)
    if not target:
        return
    saved_count = len(get_saved_bboxes(config.output_dir, effective_user_id(update)))
    await target.reply_text(
        area_home_text(saved_count),
        parse_mode=ParseMode.HTML,
        reply_markup=area_home_markup(config, effective_user_id(update)),
    )


def area_home_text(saved_count: int) -> str:
    return (
        "🗺 <b>Где собирать данные для калибровки?</b>\n"
        "Старая калибровка использовала только уже обработанные сцены. Если report.json не было, "
        "заданий тоже не было. Здесь бот сам ищет full-resolution сцену, выполняет candidate detection "
        "и формирует независимые tiles.\n\n"
        f"Встроенный каталог: <code>{len(CALIBRATION_AREAS)}</code> операционных морских секторов.\n"
        f"Сохранённые bbox: <code>{saved_count}</code>.\n\n"
        "Секторы — компактные рабочие AOI для калибровки, а не официальные границы морей. "
        "Для первичного набора обычно выбирайте <b>Sentinel-1</b>: SAR не зависит от облачности."
    )


def area_home_markup(config: TelegramBotConfig, user_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton(
                "⭐ Default AOI",
                callback_data=_cb(ACTION_AREA_SELECT, "default"),
            ),
            InlineKeyboardButton(
                "📍 Мои районы",
                callback_data=_cb(ACTION_AREA_SAVED),
            ),
        ]
    )
    for start in range(0, len(AREA_GROUPS), 2):
        row = []
        for group in AREA_GROUPS[start : start + 2]:
            row.append(
                InlineKeyboardButton(
                    f"{group.emoji} {group.name}",
                    callback_data=_cb(ACTION_AREA_GROUP, group.id, "0"),
                )
            )
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                f"📚 Все {len(CALIBRATION_AREAS)} секторов",
                callback_data=_cb(ACTION_AREA_ALL, "0"),
            )
        ]
    )
    rows.append([InlineKeyboardButton("🧪 Назад к калибровке", callback_data=_cb("open"))])
    del config, user_id
    return InlineKeyboardMarkup(rows)


async def show_group_page(
    update: Update,
    config: TelegramBotConfig,
    group_id: str,
    page: int,
) -> None:
    group = get_area_group(group_id)
    if group is None:
        await show_area_home(update, config)
        return
    areas = areas_for_group(group_id)
    await _show_area_page(update, config, areas, page, f"{group.emoji} {group.name}", group_id)


async def show_all_page(update: Update, config: TelegramBotConfig, page: int) -> None:
    await _show_area_page(
        update,
        config,
        list(CALIBRATION_AREAS),
        page,
        "📚 Все акватории",
        None,
    )


async def _show_area_page(
    update: Update,
    config: TelegramBotConfig,
    areas: list[CalibrationArea],
    page: int,
    title: str,
    group_id: str | None,
) -> None:
    target = _target(update)
    if not target:
        return
    shown, normalized, page_count = paginate_areas(areas, page)
    lines = [f"<b>{html.escape(title)}</b>", f"Страница {normalized + 1}/{page_count}.", "", "Выберите сектор:"]
    rows = [
        [
            InlineKeyboardButton(
                area.name,
                callback_data=_cb(ACTION_AREA_SELECT, f"b.{area.id}"),
            )
        ]
        for area in shown
    ]
    navigation: list[InlineKeyboardButton] = []
    action = ACTION_AREA_GROUP if group_id else ACTION_AREA_ALL
    prefix = [group_id] if group_id else []
    if normalized > 0:
        navigation.append(
            InlineKeyboardButton("⬅️", callback_data=_cb(action, *prefix, str(normalized - 1)))
        )
    navigation.append(InlineKeyboardButton(f"{normalized + 1}/{page_count}", callback_data=_cb(ACTION_AREA_HOME)))
    if normalized + 1 < page_count:
        navigation.append(
            InlineKeyboardButton("➡️", callback_data=_cb(action, *prefix, str(normalized + 1)))
        )
    rows.append(navigation)
    rows.append([InlineKeyboardButton("🗺 Категории", callback_data=_cb(ACTION_AREA_HOME))])
    await target.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )
    del config


async def show_saved_areas(update: Update, config: TelegramBotConfig) -> None:
    target = _target(update)
    if not target:
        return
    saved = get_saved_bboxes(config.output_dir, effective_user_id(update))
    if not saved:
        await target.reply_text(
            "<b>Сохранённых bbox нет.</b>\n"
            "Создайте район командой <code>/detectbbox</code> или выберите встроенную акваторию.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🗺 Акватории", callback_data=_cb(ACTION_AREA_HOME))]]
            ),
        )
        return
    rows = [
        [
            InlineKeyboardButton(
                f"{index}. {bbox.label}",
                callback_data=_cb(ACTION_AREA_SELECT, f"s.{bbox.id}"),
            )
        ]
        for index, bbox in enumerate(saved, start=1)
    ]
    rows.append([InlineKeyboardButton("🗺 Акватории", callback_data=_cb(ACTION_AREA_HOME))])
    await target.reply_text(
        "<b>Мои районы для калибровки</b>\nВыберите сохранённый bbox.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_area_sensor_choice(
    update: Update,
    config: TelegramBotConfig,
    area_ref: str,
) -> None:
    target = _target(update)
    if not target:
        return
    try:
        area = resolve_area(config, effective_user_id(update), area_ref)
    except (FileNotFoundError, ValueError) as exc:
        await target.reply_text(
            f"Не удалось открыть район: {html.escape(str(exc))}",
            parse_mode=ParseMode.HTML,
            reply_markup=area_home_markup(config, effective_user_id(update)),
        )
        return
    west, south, east, north = area["bbox"]
    s2_note = (
        "Sentinel-2 single-band разрешён только как явный research-режим."
        if sentinel2_single_band_enabled()
        else (
            "Sentinel-2 operational пока недоступен: нужен согласованный стек "
            "B02/B03/B04/B08 и SCL/cloud/water masks."
        )
    )
    text = (
        f"🗺 <b>{html.escape(str(area['name']))}</b>\n"
        f"Источник: <code>{html.escape(str(area['source']))}</code>\n"
        f"bbox: <code>{west:g}, {south:g}, {east:g}, {north:g}</code>\n\n"
        "Выберите сенсор. <b>Sentinel-1</b> — текущий operational baseline. "
        f"{s2_note}"
    )
    await target.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=area_sensor_markup(area_ref),
    )


def area_sensor_markup(area_ref: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "📡 Sentinel-1 · operational",
                callback_data=_cb(ACTION_AREA_SENSOR, area_ref, "s1"),
            )
        ]
    ]
    if sentinel2_single_band_enabled():
        rows.append(
            [
                InlineKeyboardButton(
                    "🧪 Sentinel-2 single-band · research",
                    callback_data=_cb(ACTION_AREA_SENSOR, area_ref, "s2"),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    "🚫 Sentinel-2 · multiband stack не готов",
                    callback_data=_cb(ACTION_AREA_S2_INFO, area_ref),
                )
            ]
        )
    rows.extend(
        [
            [
                InlineKeyboardButton(
                    "🔄 Auto · Sentinel-1 сначала",
                    callback_data=_cb(ACTION_AREA_SENSOR, area_ref, "auto"),
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Акватории",
                    callback_data=_cb(ACTION_AREA_HOME),
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


async def show_sentinel2_not_ready(update: Update, area_ref: str) -> None:
    target = _target(update)
    if not target:
        return
    await target.reply_text(
        "Sentinel-2 single-band нельзя использовать как operational detector. "
        "Для корректного optical-контура нужны совместно выровненные B02/B03/B04/B08, "
        "SCL, cloud mask и water mask. До реализации этого стека используйте Sentinel-1.",
        reply_markup=area_sensor_markup(area_ref),
    )


async def show_period_choice(
    update: Update,
    config: TelegramBotConfig,
    area_ref: str,
    sensor_code: str,
) -> None:
    target = _target(update)
    if not target:
        return
    try:
        sensor = _sensor(sensor_code)
        area = resolve_area(config, effective_user_id(update), area_ref)
    except (FileNotFoundError, ValueError) as exc:
        await target.reply_text(f"Ошибка выбора: {exc}", reply_markup=area_home_markup(config, effective_user_id(update)))
        return
    labels = {24: "24 ч", 72: "3 дня", 168: "7 дней", 336: "14 дней", 720: "30 дней"}
    rows = []
    for start in range(0, len(PERIODS), 2):
        rows.append(
            [
                InlineKeyboardButton(
                    labels[hours],
                    callback_data=_cb(ACTION_AREA_SEARCH, area_ref, sensor_code, str(hours)),
                )
                for hours in PERIODS[start : start + 2]
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Сенсор", callback_data=_cb(ACTION_AREA_SELECT, area_ref))])
    await target.reply_text(
        f"<b>{html.escape(str(area['name']))}</b>\n"
        f"sensor: <code>{sensor.value}</code>\n\n"
        "За какой период искать detection-capable сцены? Для редких покрытий выбирайте 14–30 дней.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def search_area(
    update: Update,
    config: TelegramBotConfig,
    area_ref: str,
    sensor_code: str,
    hours: int,
) -> None:
    target = _target(update)
    if not target:
        return
    try:
        area = resolve_area(config, effective_user_id(update), area_ref)
        sensor = _sensor(sensor_code)
    except (FileNotFoundError, ValueError) as exc:
        await target.reply_text(f"Ошибка выбора акватории: {exc}", reply_markup=area_home_markup(config, effective_user_id(update)))
        return
    status = await target.reply_text(
        f"⏳ Ищу сцены для калибровки\n{area['name']}\nsensor={sensor.value}, период={hours} ч"
    )
    try:
        session = await asyncio.to_thread(
            search_calibration_scenes,
            output_dir=config.output_dir,
            area_id=str(area["id"]),
            area_name=str(area["name"]),
            area_source=str(area["source"]),
            aoi_geojson=area["geojson"],
            sensor=sensor,
            hours=hours,
            max_results=config.max_results,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
        )
    except Exception as exc:  # noqa: BLE001 - provider errors are user-facing
        await status.edit_text(
            "Сцены для калибровки не найдены.\n"
            f"Причина: {exc}\n\n"
            "Попробуйте Sentinel-1, период 14–30 дней или соседний сектор.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("↻ Изменить период", callback_data=_cb(ACTION_AREA_SENSOR, area_ref, sensor_code))],
                    [InlineKeyboardButton("🗺 Другая акватория", callback_data=_cb(ACTION_AREA_HOME))],
                ]
            ),
        )
        return
    await status.edit_text(
        search_result_text(session),
        parse_mode=ParseMode.HTML,
        reply_markup=search_result_markup(session),
    )


def search_result_text(session: dict[str, Any]) -> str:
    area = session.get("area") if isinstance(session.get("area"), dict) else {}
    request = session.get("request") if isinstance(session.get("request"), dict) else {}
    result = session.get("result") if isinstance(session.get("result"), dict) else {}
    scenes = result.get("scenes") if isinstance(result.get("scenes"), list) else []
    cache = "hit" if result.get("cache_hit") else "refresh"
    return (
        "✅ <b>Сцены найдены</b>\n"
        f"Акватория: <b>{html.escape(str(area.get('name') or 'unknown'))}</b>\n"
        f"sensor: <code>{html.escape(str(result.get('sensor') or request.get('sensor')))}</code> · "
        f"provider: <code>{html.escape(str(result.get('provider') or 'unknown'))}</code>\n"
        f"период: <code>{int(request.get('hours') or 0)} ч</code> · cache: <code>{cache}</code>\n"
        f"сцен: <code>{len(scenes)}</code>\n\n"
        "Выберите одну сцену либо обработайте до трёх свежих сцен. Обработка создаст report.json, "
        "candidate-задачи и независимые phase 2 tiles."
    )


def search_result_markup(session: dict[str, Any]) -> InlineKeyboardMarkup:
    result = session.get("result") if isinstance(session.get("result"), dict) else {}
    scenes = result.get("scenes") if isinstance(result.get("scenes"), list) else []
    rows: list[list[InlineKeyboardButton]] = []
    for index, scene in enumerate(scenes[:6], start=1):
        if not isinstance(scene, dict) or not scene.get("token"):
            continue
        timestamp = str(scene.get("acquisition_time") or "unknown").replace("T", " ")[:16]
        provider = str(scene.get("provider") or "")[:12]
        rows.append(
            [
                InlineKeyboardButton(
                    f"{index}. {timestamp} · {provider}",
                    callback_data=_cb(ACTION_AREA_RUN, str(scene["token"])),
                )
            ]
        )
    if len(scenes) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    "⚙️ Подготовить до 3 свежих сцен",
                    callback_data=_cb(ACTION_AREA_BATCH, str(session["session_id"]), "3"),
                )
            ]
        )
    rows.append([InlineKeyboardButton("🗺 Другая акватория", callback_data=_cb(ACTION_AREA_HOME))])
    return InlineKeyboardMarkup(rows)


async def prepare_session(
    update: Update,
    config: TelegramBotConfig,
    session_id: str,
    limit: int,
) -> None:
    try:
        session = load_search_session(
            config.output_dir,
            session_id,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
        )
        tokens = session_tokens(session, limit)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        target = _target(update)
        if target:
            await target.reply_text(
                f"Сессия поиска недоступна: {exc}",
                reply_markup=area_home_markup(config, effective_user_id(update)),
            )
        return
    await prepare_tokens(update, config, tokens)


async def prepare_tokens(
    update: Update,
    config: TelegramBotConfig,
    tokens: list[str],
) -> None:
    target = _target(update)
    if not target:
        return
    if not tokens:
        await target.reply_text("В сессии нет сцен для обработки.", reply_markup=area_home_markup(config, effective_user_id(update)))
        return
    status = await target.reply_text(f"⏳ Подготавливаю калибровочный набор · сцен: {len(tokens)}")
    loop = asyncio.get_running_loop()

    def progress(stage: str) -> None:
        asyncio.run_coroutine_threadsafe(
            status.edit_text(f"⏳ Калибровка · {stage}"),
            loop,
        )

    try:
        result = await asyncio.to_thread(
            prepare_calibration_data,
            output_dir=config.output_dir,
            tokens=tokens,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            max_crops=0,
            land_mask_geojson=config.land_mask_geojson,
            shoreline_buffer_m=config.shoreline_buffer_m,
            phase2_targets=phase2_targets(config),
            context_geojson=context_geojson(),
            progress_callback=progress,
        )
    except Exception as exc:  # noqa: BLE001 - materialization/provider errors are user-facing
        await status.edit_text(
            f"Не удалось подготовить калибровочные данные: {exc}",
            reply_markup=area_home_markup(config, effective_user_id(update)),
        )
        return

    failed = len(result.failed_tokens)
    zero_note = (
        "\nНа сценах нет candidates, но независимые tiles созданы — начинайте phase 2."
        if result.candidate_count == 0
        else ""
    )
    await status.edit_text(
        "✅ Калибровочный набор подготовлен\n"
        f"сцен обработано: {len(result.processed_tokens)} · ошибок: {failed}\n"
        f"candidates: {result.candidate_count}\n"
        f"phase 2 tiles всего: {result.phase2_task_count}"
        f"{zero_note}",
        reply_markup=preparation_result_markup(result.candidate_count),
    )
    if len(result.overviews) == 1 and result.overviews[0].is_file():
        try:
            with result.overviews[0].open("rb") as file_obj:
                await target.reply_photo(
                    photo=file_obj,
                    caption="Обзор сцены, подготовленной для калибровки",
                )
        except Exception:
            pass


def preparation_result_markup(candidate_count: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if candidate_count > 0:
        rows.append([InlineKeyboardButton("🧪 Размечать candidates", callback_data=_cb("next"))])
    rows.append([InlineKeyboardButton("🌊 Размечать независимые tiles", callback_data=_cb("p2next"))])
    rows.append([InlineKeyboardButton("🗺 Другая акватория", callback_data=_cb(ACTION_AREA_HOME))])
    rows.append([InlineKeyboardButton("📊 Калибровка", callback_data=_cb("open"))])
    return InlineKeyboardMarkup(rows)


def resolve_area(config: TelegramBotConfig, user_id: int, area_ref: str) -> dict[str, Any]:
    if area_ref == "default":
        if not config.default_aoi.is_file():
            raise FileNotFoundError(f"Default AOI not found: {config.default_aoi}")
        geojson = read_geojson(config.default_aoi)
        bbox = _geojson_bbox(geojson)
        return {
            "id": "default",
            "name": "Default AOI",
            "source": "default_aoi",
            "bbox": bbox,
            "geojson": geojson,
            "default_sensor": config.default_sensor,
            "default_hours": config.default_lookback_hours,
        }
    if area_ref.startswith("b."):
        area = get_calibration_area(area_ref[2:])
        if area is None:
            raise ValueError(f"Unknown calibration area: {area_ref}")
        return {
            "id": area.id,
            "name": area.name,
            "source": "built_in_catalog",
            "bbox": area.bbox,
            "geojson": area.geojson(),
            "default_sensor": Sensor.SENTINEL1,
            "default_hours": area.default_hours,
        }
    if area_ref.startswith("s."):
        saved: SavedBbox | None = get_saved_bbox(config.output_dir, user_id, area_ref[2:])
        if saved is None:
            raise ValueError("Saved bbox no longer exists")
        return {
            "id": f"saved_{saved.id}",
            "name": saved.label,
            "source": "saved_bbox",
            "bbox": (saved.west, saved.south, saved.east, saved.north),
            "geojson": bbox_geojson(saved.west, saved.south, saved.east, saved.north),
            "default_sensor": saved.sensor,
            "default_hours": saved.hours,
        }
    raise ValueError(f"Unsupported area reference: {area_ref}")


def _geojson_bbox(payload: dict[str, object]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []

    def walk(value: object) -> None:
        if isinstance(value, list):
            if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
                points.append((float(value[0]), float(value[1])))
                return
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            if "coordinates" in value:
                walk(value["coordinates"])
            elif "geometry" in value:
                walk(value["geometry"])
            elif "features" in value:
                walk(value["features"])

    walk(payload)
    if not points:
        raise ValueError("AOI GeoJSON has no coordinates")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _target(update: Update):
    return update.effective_message or (update.callback_query.message if update.callback_query else None)


def _is_admin(update: Update, config: TelegramBotConfig) -> bool:
    return bool(config.admin_ids) and effective_user_id(update) in config.admin_ids


def _sensor(code: str) -> Sensor:
    try:
        return SENSOR_CODES[code]
    except KeyError as exc:
        raise ValueError(f"Unknown sensor code: {code}") from exc


def _page(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def _hours(value: str) -> int:
    try:
        hours = int(value)
    except ValueError as exc:
        raise ValueError("Invalid search period") from exc
    if hours not in PERIODS:
        raise ValueError("Unsupported search period")
    return hours


def _batch_limit(value: str) -> int:
    try:
        return max(1, min(3, int(value)))
    except ValueError:
        return 1


def _cb(action: str, *parts: str) -> str:
    value = ":".join((CALLBACK_PREFIX, action, *parts))
    if len(value.encode("utf-8")) > 64:
        raise ValueError(f"Telegram callback_data is too long: {value}")
    return value
