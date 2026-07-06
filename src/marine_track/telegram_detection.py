from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.detection_scene_search import search_detection_capable_scenes
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

DETECT_CALLBACK_PREFIX = "mtdetect"


async def detect_command(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if not args:
        await message.reply_text(
            "Формат: /detect <token>. Token берется из /dates или /bboxdates."
        )
        return
    await send_detection_by_token(update, args[0].strip(), config)


async def detect_bbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if len(args) < 5:
        await message.reply_text(
            "Формат: /detectbbox [auto|sentinel1|sentinel2] west south east north [hours]\n"
            "Пример: /detectbbox sentinel1 36.5 43.8 38.5 45.0 12"
        )
        return
    try:
        sensor = parse_scene_sensor(args[0], config.default_sensor)
        west, south, east, north = [float(value) for value in args[1:5]]
        hours = parse_scene_hours(args[5] if len(args) > 5 else None, DEFAULT_HOURS)
        aoi_geojson = bbox_geojson(west, south, east, north)
        aoi_path = write_temp_aoi(aoi_geojson)
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}")
        return

    start, end = utc_window(hours)
    search_dir = run_dir(config.output_dir, "detectbbox")
    status = await message.reply_text(
        "⏳ Ищу обрабатываемые GeoTIFF/COG сцены: "
        f"sensor={sensor.value}, bbox={west},{south},{east},{north}, период={hours} ч"
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
            aoi_geojson=aoi_geojson,
        )
    except Exception as exc:
        await status.edit_text(f"Ошибка поиска detection-capable сцен: {exc}")
        return
    finally:
        aoi_path.unlink(missing_ok=True)

    if not tokens:
        await status.edit_text("Не найдено сцен с GeoTIFF/COG assets для детекции.")
        return
    token = tokens[0]
    first_scene = result.scenes[0]
    search_cache_status = "hit" if result.cache_hit else "refresh"
    await status.edit_text(
        "Найдена сцена для детекции:\n"
        f"token: {token}\n"
        f"provider: {result.provider}\n"
        f"sensor: {result.sensor.value}\n"
        f"search_cache: {search_cache_status}\n"
        f"time: {first_scene.acquisition_time.isoformat()}\n"
        f"product: {first_scene.product_id[:120]}\n\n"
        "Запускаю обработку."
    )
    await send_detection_by_token(update, token, config)


async def detect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    prefix, _, token = query.data.partition(":")
    if prefix != DETECT_CALLBACK_PREFIX or not token:
        return
    await send_detection_by_token(update, token, config)


async def send_detection_by_token(update: Update, token: str, config: TelegramBotConfig) -> None:
    target = update.effective_message
    query = update.callback_query
    if query:
        await query.answer()
    if not target and query:
        target = query.message
    if not target:
        return

    status = await target.reply_text(f"⏳ Запускаю детекцию по scene token: {token}")
    try:
        result = await asyncio.to_thread(
            run_detection_for_token,
            token=token,
            output_dir=config.output_dir,
            max_crops=config.detection_max_crops,
            threshold_sigma=3.5,
            min_area_px=2,
            max_area_px=5000,
            local_window_px=31,
            guard_window_px=5,
            land_mask_geojson=config.land_mask_geojson,
            shoreline_buffer_m=config.shoreline_buffer_m,
        )
    except MaterializationError as exc:
        await status.edit_text(
            "Детекция не запущена: нет подходящего full-resolution GeoTIFF/COG asset.\n"
            f"Причина: {exc}\n\n"
            "Это нормально для ASF ZIP/GRD и preview-only сцен. Для MVP-детекции нужен RTC/COG asset."
        )
        return
    except Exception as exc:
        await status.edit_text(f"Ошибка детекции: {exc}")
        return

    await status.edit_text(summary_text(result))
    await send_detection_outputs(target, result)


def summary_text(result: DetectionRunResult) -> str:
    scene = result.materialized.scene
    crop_status = "yes" if result.materialized.cropped else "no"
    raster_cache_status = "hit" if result.materialized.cache_hit else "created"
    return (
        "✅ Детекция завершена\n"
        f"token: {result.token}\n"
        f"sensor: {scene.sensor.value}\n"
        f"provider: {result.materialized.provider}\n"
        f"time: {scene.acquisition_time.isoformat()}\n"
        f"product: {scene.product_id[:120]}\n"
        f"detections: {len(result.detections)}\n"
        f"raster: {result.materialized.raster_key}\n"
        f"raster_cache: {raster_cache_status}\n"
        f"aoi_crop: {crop_status}"
    )


async def send_detection_outputs(target, result: DetectionRunResult) -> None:
    await send_photo_or_document(target, result.overview_png, caption="Общий снимок с точками судов")
    for index, crop in enumerate(result.crop_pngs, start=1):
        await send_photo_or_document(target, crop, caption=f"Судно #{index}")
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
