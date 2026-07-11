from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Message, Update
from telegram.ext import ContextTypes

from marine_track.bounded_detection import (
    DetectionProcessError,
    DetectionTimeoutError,
    run_detection_in_subprocess,
)
from marine_track.detection_pipeline import DetectionRunResult
from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.provider_canary import build_canary_aoi
from marine_track.scene_materializer import MaterializationError
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_scene_browser import (
    DEFAULT_HOURS,
    bbox_geojson,
    parse_scene_hours,
    parse_scene_sensor,
    register_scenes,
    run_dir,
    utc_window,
    write_temp_aoi,
)
from marine_track.telegram_ui import main_menu_markup
from marine_track.telegram_user_state import (
    OUTPUT_MODE_ALL,
    OUTPUT_MODE_FILES,
    OUTPUT_MODE_IMAGES,
    get_output_mode,
    get_saved_bboxes,
    output_mode_label,
    save_last_bbox,
)

DETECT_CALLBACK_PREFIX = "mtdetect"


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def menu_for_user(update: Update, config: TelegramBotConfig):
    count = len(get_saved_bboxes(config.output_dir, effective_user_id(update)))
    return main_menu_markup(has_last_bbox=count > 0, bbox_count=count)


def output_mode_for_user(update: Update, config: TelegramBotConfig) -> str:
    return get_output_mode(config.output_dir, effective_user_id(update))


def progress_text(stage: str, detail: str | None = None) -> str:
    text = f"⏳ {stage}"
    if detail:
        text += f"\n{detail}"
    return text


def make_progress_callback(loop: asyncio.AbstractEventLoop, status: Message):
    def callback(stage: str) -> None:
        asyncio.run_coroutine_threadsafe(status.edit_text(progress_text(stage)), loop)

    return callback


def compact_default_detection_aoi(config: TelegramBotConfig):
    side_km = float(config.default_detection_side_km)
    return build_canary_aoi(
        base_dir=Path("."),
        default_aoi=config.default_aoi,
        side_km=side_km,
        max_area_km2=min(625.0, side_km * side_km * 1.05),
    )


async def detect_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if not args:
        await message.reply_text(
            "Формат: /detect <token>. Проще: нажмите 🔎 у сцены или используйте /detectbbox.",
            reply_markup=menu_for_user(update, config),
        )
        return
    await send_detection_by_token(update, args[0].strip(), config)


async def detect_default_aoi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    target = update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )
    if not target:
        return
    if not config.default_aoi.is_file():
        await target.reply_text(
            f"AOI не найден: {config.default_aoi}\nПроверьте MARINE_TRACK_DEFAULT_AOI.",
            reply_markup=menu_for_user(update, config),
        )
        return
    try:
        compact_aoi = await asyncio.to_thread(compact_default_detection_aoi, config)
        aoi_geojson = compact_aoi.payload
        aoi_path = write_temp_aoi(aoi_geojson)
    except Exception as exc:
        await target.reply_text(
            f"Не удалось подготовить безопасный сектор AOI: {exc}",
            reply_markup=menu_for_user(update, config),
        )
        return

    hours = config.default_lookback_hours
    sensor = config.default_sensor
    start, end = utc_window(hours)
    search_dir = run_dir(config.output_dir, "detect_default")
    status = await target.reply_text(
        progress_text(
            "1/5 search · свежая сцена по bounded AOI",
            f"sensor={sensor.value}, период={hours} ч, "
            f"sector={compact_aoi.area_km2:.1f} km²",
        )
    )
    try:
        result = await asyncio.to_thread(
            search_detection_capable_scenes,
            aoi_path,
            start,
            end,
            sensor,
            search_dir,
            config.max_results,
        )
        tokens = register_scenes(
            config.output_dir,
            result.provider,
            result.sensor,
            result.scenes,
            result.scenes_json,
            result.asset_manifest,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            aoi_geojson=aoi_geojson,
            search_hours=hours,
        )
    except Exception as exc:
        await status.edit_text(f"Не удалось найти сцену для candidate detection: {exc}")
        return
    finally:
        aoi_path.unlink(missing_ok=True)
    if not tokens:
        await status.edit_text("Нет сцен с GeoTIFF/COG assets для candidate detection.")
        return
    scene = result.scenes[0]
    cache_status = "hit" if result.cache_hit else "refresh"
    await status.edit_text(
        progress_text(
            "1/5 search · сцена выбрана",
            f"provider={result.provider}\nsensor={result.sensor.value}\n"
            f"search_cache={cache_status}\ntime={scene.acquisition_time.isoformat()}\n"
            f"aoi={compact_aoi.area_km2:.1f} km² (bounded)",
        )
    )
    await send_detection_by_token(update, tokens[0], config)


async def detect_bbox_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if len(args) < 5:
        await message.reply_text(
            "Формат: /detectbbox [auto|sentinel1|sentinel2] west south east north [hours]\n"
            "Пример: /detectbbox sentinel1 36.5 43.8 38.5 45.0 12",
            reply_markup=menu_for_user(update, config),
        )
        return
    try:
        sensor = parse_scene_sensor(args[0], config.default_sensor)
        west, south, east, north = [float(value) for value in args[1:5]]
        hours = parse_scene_hours(args[5] if len(args) > 5 else None, DEFAULT_HOURS)
        aoi_geojson = bbox_geojson(west, south, east, north)
        aoi_path = write_temp_aoi(aoi_geojson)
        save_last_bbox(
            config.output_dir,
            effective_user_id(update),
            sensor,
            west,
            south,
            east,
            north,
            hours,
        )
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}", reply_markup=menu_for_user(update, config))
        return

    start, end = utc_window(hours)
    search_dir = run_dir(config.output_dir, "detectbbox")
    status = await message.reply_text(
        progress_text(
            "1/5 search · detection-capable GeoTIFF/COG",
            f"sensor={sensor.value}, bbox={west},{south},{east},{north}, период={hours} ч",
        )
    )
    try:
        result = await asyncio.to_thread(
            search_detection_capable_scenes,
            aoi_path,
            start,
            end,
            sensor,
            search_dir,
            config.max_results,
        )
        tokens = register_scenes(
            config.output_dir,
            result.provider,
            result.sensor,
            result.scenes,
            result.scenes_json,
            result.asset_manifest,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            aoi_geojson=aoi_geojson,
            search_hours=hours,
        )
    except Exception as exc:
        await status.edit_text(f"Ошибка поиска detection-capable сцен: {exc}")
        return
    finally:
        aoi_path.unlink(missing_ok=True)

    if not tokens:
        await status.edit_text("Не найдено сцен с GeoTIFF/COG assets для candidate detection.")
        return
    token = tokens[0]
    first_scene = result.scenes[0]
    search_cache_status = "hit" if result.cache_hit else "refresh"
    await status.edit_text(
        progress_text(
            "1/5 search · сцена выбрана",
            f"provider={result.provider}\nsensor={result.sensor.value}\n"
            f"search_cache={search_cache_status}\ntime={first_scene.acquisition_time.isoformat()}",
        )
    )
    await send_detection_by_token(update, token, config)


async def detect_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: TelegramBotConfig,
) -> None:
    del context
    query = update.callback_query
    if not query or not query.data:
        return
    prefix, _, token = query.data.partition(":")
    if prefix != DETECT_CALLBACK_PREFIX or not token:
        return
    await send_detection_by_token(update, token, config)


async def send_detection_by_token(
    update: Update,
    token: str,
    config: TelegramBotConfig,
) -> None:
    target = update.effective_message
    query = update.callback_query
    if query:
        await query.answer()
    if not target and query:
        target = query.message
    if not target:
        return

    output_mode = output_mode_for_user(update, config)
    status = await target.reply_text(
        progress_text(
            "1/5 prepare · scene token",
            f"token={token}\nвыдача={output_mode_label(output_mode)}",
        )
    )
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.to_thread(
            run_detection_in_subprocess,
            token=token,
            output_dir=config.output_dir,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
            max_crops=config.detection_max_crops,
            land_mask_geojson=config.land_mask_geojson,
            shoreline_buffer_m=config.shoreline_buffer_m,
            timeout_s=float(config.detection_job_timeout_s),
            progress_callback=make_progress_callback(loop, status),
        )
    except DetectionTimeoutError as exc:
        await status.edit_text(
            "Обработка остановлена по безопасному лимиту времени; зависший worker завершён.\n"
            f"Причина: {exc}\n"
            "Уменьшите AOI или повторите позже.",
            reply_markup=menu_for_user(update, config),
        )
        return
    except MaterializationError as exc:
        await status.edit_text(
            "Обработка не запущена: нет доступного full-resolution GeoTIFF/COG asset.\n"
            f"Причина: {exc}\n\n"
            "Бесплатный Planetary Computer используется без пользовательского токена. "
            "CDSE/Sentinel Hub подключаются только при явно настроенных credentials.",
            reply_markup=menu_for_user(update, config),
        )
        return
    except DetectionProcessError as exc:
        await status.edit_text(
            f"Ошибка изолированного candidate detection worker: {exc}",
            reply_markup=menu_for_user(update, config),
        )
        return
    except Exception as exc:
        await status.edit_text(
            f"Ошибка candidate detection: {exc}",
            reply_markup=menu_for_user(update, config),
        )
        return

    await status.edit_text(
        progress_text(
            "5/5 send · отправка результатов",
            f"candidates={len(result.detections)}\nвыдача={output_mode_label(output_mode)}",
        )
    )
    await send_detection_outputs(target, result, output_mode)
    await status.edit_text(
        summary_text(result, output_mode), reply_markup=menu_for_user(update, config)
    )


def summary_text(result: DetectionRunResult, output_mode: str = OUTPUT_MODE_ALL) -> str:
    scene = result.materialized.scene
    crop_status = "yes" if result.materialized.cropped else "no"
    raster_cache_status = "hit" if result.materialized.cache_hit else "created"
    ais_references = sum(item.references.ais is not None for item in result.detections)
    kelvin_proxies = sum(
        item.research_proxies.kelvin_speed is not None for item in result.detections
    )
    return (
        "✅ Candidate detection завершена\n"
        f"sensor: {scene.sensor.value}\n"
        f"provider: {result.materialized.provider}\n"
        f"time: {scene.acquisition_time.isoformat()}\n"
        f"vessel_candidates: {len(result.detections)}\n"
        f"AIS references: {ais_references}\n"
        f"Kelvin research proxies: {kelvin_proxies}\n"
        "operational_speed: not_estimated unless explicitly stated\n"
        f"raster_cache: {raster_cache_status}\n"
        f"aoi_crop: {crop_status}\n"
        f"output_mode: {output_mode_label(output_mode)}\n"
        f"token: {result.token}"
    )


async def send_detection_outputs(
    target,
    result: DetectionRunResult,
    output_mode: str = OUTPUT_MODE_ALL,
) -> None:
    if output_mode in {OUTPUT_MODE_ALL, OUTPUT_MODE_IMAGES}:
        await send_photo_or_document(target, result.overview_png, caption="Обзор кандидатов судов")
        for index, crop in enumerate(result.crop_pngs, start=1):
            await send_photo_or_document(target, crop, caption=f"Кандидат #{index}")
    if output_mode in {OUTPUT_MODE_ALL, OUTPUT_MODE_FILES}:
        for path in (result.geojson, result.csv, result.parquet, result.report_json):
            await send_document(target, path)


async def send_photo_or_document(target, path: Path, caption: str) -> None:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        with path.open("rb") as file_obj:
            await target.reply_photo(photo=file_obj, caption=caption)
    else:
        await send_document(target, path, caption=caption)


async def send_document(target, path: Path, caption: str | None = None) -> None:
    with path.open("rb") as file_obj:
        await target.reply_document(document=file_obj, caption=caption)
