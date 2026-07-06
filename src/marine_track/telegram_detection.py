from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.scene_materializer import MaterializationError
from marine_track.telegram_config import TelegramBotConfig

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
        result = await asyncio.to_thread(run_detection_for_token, token, config.output_dir)
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
    return (
        "✅ Детекция завершена\n"
        f"token: {result.token}\n"
        f"sensor: {scene.sensor.value}\n"
        f"provider: {result.materialized.provider}\n"
        f"time: {scene.acquisition_time.isoformat()}\n"
        f"product: {scene.product_id[:120]}\n"
        f"detections: {len(result.detections)}\n"
        f"raster: {result.materialized.raster_key}"
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
