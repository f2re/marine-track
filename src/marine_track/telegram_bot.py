from __future__ import annotations

import asyncio
import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from marine_track.models import Scene, Sensor
from marine_track.pipeline import run_search_stage
from marine_track.telegram_commands import BOT_COMMAND_LINES
from marine_track.telegram_config import TelegramBotConfig, load_telegram_config
from marine_track.telegram_scene_browser import (
    CALLBACK_PREFIX,
    bbox_dates_command as scene_bbox_dates_command,
    image_callback as scene_image_callback,
    image_command as scene_image_command,
    list_dates_command as scene_dates_command,
)

CONFIG: TelegramBotConfig | None = None
JOB_SEMAPHORE: asyncio.Semaphore | None = None


HELP_TEXT = """<b>Marine Track Bot</b>

Бот ищет оперативные открытые спутниковые сцены для MVP обнаружения судов и кильватерных следов.

Команды:
<code>/search [auto|sentinel1|sentinel2] [hours]</code>
Поиск сцен по AOI из .env. Пример: <code>/search sentinel1 72</code>

<code>/dates [auto|sentinel1|sentinel2] [hours]</code>
Доступные сроки снимков по AOI из .env. По умолчанию последние 12 часов.

<code>/bbox [auto|sentinel1|sentinel2] west south east north [hours]</code>
Поиск по прямоугольнику. Пример: <code>/bbox sentinel1 36.5 43.8 38.5 45.0 72</code>

<code>/bboxdates [auto|sentinel1|sentinel2] west south east north [hours]</code>
Сроки снимков по прямоугольнику. Пример: <code>/bboxdates sentinel1 36.5 43.8 38.5 45.0 12</code>

<code>/image token</code> — отправить preview/quicklook для ранее найденного срока.
<code>/status</code> — конфигурация и ограничения.
<code>/whoami</code> — ваш Telegram user id для TELEGRAM_ADMIN_IDS.
"""


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
    user = update.effective_user
    return int(getattr(user, "id", 0) or 0)


def is_authorized(update: Update) -> bool:
    config = get_config()
    if not config.admin_ids:
        return True
    return effective_user_id(update) in config.admin_ids


async def require_authorized(update: Update) -> bool:
    if is_authorized(update):
        return True
    message = update.effective_message
    if message:
        await message.reply_text(
            "Доступ к рабочим командам закрыт. "
            f"Ваш Telegram user id: {effective_user_id(update)}. "
            "Добавьте его в TELEGRAM_ADMIN_IDS."
        )
    return False


def parse_sensor(value: str | None, default: Sensor) -> Sensor:
    if not value:
        return default
    normalized = value.strip().lower()
    aliases = {"s1": "sentinel1", "sar": "sentinel1", "s2": "sentinel2", "optical": "sentinel2"}
    normalized = aliases.get(normalized, normalized)
    try:
        return Sensor(normalized)
    except ValueError as exc:
        raise ValueError("sensor должен быть auto, sentinel1 или sentinel2") from exc


def parse_hours(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        hours = int(value)
    except ValueError as exc:
        raise ValueError("hours должен быть целым числом") from exc
    if hours <= 0 or hours > 24 * 30:
        raise ValueError("hours должен быть в диапазоне 1..720")
    return hours


def time_window(hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    return start, end


def make_run_dir(base_dir: Path, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base_dir / f"{prefix}_{stamp}"


def bbox_geojson(west: float, south: float, east: float, north: float) -> dict[str, object]:
    if not (-180.0 <= west <= 180.0 and -180.0 <= east <= 180.0):
        raise ValueError("west/east должны быть в диапазоне -180..180")
    if not (-90.0 <= south <= 90.0 and -90.0 <= north <= 90.0):
        raise ValueError("south/north должны быть в диапазоне -90..90")
    if east <= west or north <= south:
        raise ValueError("bbox должен задаваться как west south east north")
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "telegram_bbox"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[west, south], [east, south], [east, north], [west, north], [west, south]]
                    ],
                },
            }
        ],
    }


def write_temp_aoi(payload: dict[str, object]) -> Path:
    tmp = NamedTemporaryFile("w", suffix=".geojson", prefix="marine_track_bbox_", delete=False)
    with tmp:
        json.dump(payload, tmp)
    return Path(tmp.name)


def format_scene_table(provider: str, sensor: Sensor, scenes: list[Scene], max_rows: int = 8) -> str:
    lines = [f"provider: {provider}", f"sensor: {sensor.value}", f"scenes: {len(scenes)}", ""]
    for index, scene in enumerate(scenes[:max_rows], start=1):
        product = scene.product_id[:72]
        lines.append(f"{index}. {scene.acquisition_time.isoformat()}")
        lines.append(f"   {product}")
        lines.append(f"   beam={scene.beam_mode or '-'} pol/cloud={scene.polarization_label()}")
    if len(scenes) > max_rows:
        lines.append(f"... ещё {len(scenes) - max_rows}")
    return "<pre>" + html.escape("\n".join(lines)) + "</pre>"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    await message.reply_text(
        "🚢 Marine Track\n\n"
        "MVP для поиска Sentinel-1/Sentinel-2 сцен под задачу обнаружения судов и кильватерных следов.\n\n"
        "Сроки снимков: /dates или /bboxdates. Справка: /help"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(HELP_TEXT, parse_mode=ParseMode.HTML)


async def whoami_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message:
        await message.reply_text(f"Ваш Telegram user id: {effective_user_id(update)}")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    config = get_config()
    lines = [
        "⚙️ Marine Track Bot",
        f"default_aoi: {config.default_aoi}",
        f"output_dir: {config.output_dir}",
        f"default_sensor: {config.default_sensor.value}",
        f"default_lookback_hours: {config.default_lookback_hours}",
        f"max_results: {config.max_results}",
        f"max_concurrent_jobs: {config.max_concurrent_jobs}",
        f"admin_restricted: {'yes' if config.admin_ids else 'no'}",
        "",
        "commands:",
        *BOT_COMMAND_LINES,
    ]
    await message.reply_text("<pre>" + html.escape("\n".join(lines)) + "</pre>", parse_mode=ParseMode.HTML)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not await require_authorized(update):
        return
    config = get_config()
    args = list(context.args or [])
    try:
        sensor = parse_sensor(args[0] if args else None, config.default_sensor)
        hours = parse_hours(args[1] if len(args) > 1 else None, config.default_lookback_hours)
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}\nПример: /search sentinel1 72")
        return
    if not config.default_aoi.is_file():
        await message.reply_text(f"Ошибка: AOI не найден: {config.default_aoi}")
        return

    start, end = time_window(hours)
    out_dir = make_run_dir(config.output_dir, "search")
    status = await message.reply_text(
        f"⏳ Ищу сцены: sensor={sensor.value}, период={hours} ч, AOI={config.default_aoi}"
    )
    try:
        async with get_semaphore():
            result = await asyncio.to_thread(
                run_search_stage,
                config.default_aoi,
                start,
                end,
                sensor,
                out_dir,
                config.max_results,
                True,
            )
    except Exception as exc:
        await status.edit_text(f"Ошибка поиска сцен: {exc}")
        return

    scenes = json.loads(result.scenes_json.read_text(encoding="utf-8"))
    scene_models = [Scene.model_validate(item) for item in scenes]
    await status.edit_text(
        format_scene_table(result.provider, result.sensor, scene_models),
        parse_mode=ParseMode.HTML,
    )
    await message.reply_text(
        "Сохранено:\n"
        f"scenes: <code>{html.escape(str(result.scenes_json))}</code>\n"
        f"assets: <code>{html.escape(str(result.asset_manifest or 'disabled'))}</code>",
        parse_mode=ParseMode.HTML,
    )


async def bbox_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not await require_authorized(update):
        return
    config = get_config()
    args = list(context.args or [])
    if len(args) < 5:
        await message.reply_text(
            "Формат: /bbox [auto|sentinel1|sentinel2] west south east north [hours]\n"
            "Пример: /bbox sentinel1 36.5 43.8 38.5 45.0 72"
        )
        return
    try:
        sensor = parse_sensor(args[0], config.default_sensor)
        west, south, east, north = [float(value) for value in args[1:5]]
        hours = parse_hours(args[5] if len(args) > 5 else None, config.default_lookback_hours)
        aoi_path = write_temp_aoi(bbox_geojson(west, south, east, north))
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}")
        return

    start, end = time_window(hours)
    out_dir = make_run_dir(config.output_dir, "bbox")
    status = await message.reply_text(
        f"⏳ Ищу сцены: sensor={sensor.value}, bbox={west},{south},{east},{north}, период={hours} ч"
    )
    try:
        async with get_semaphore():
            result = await asyncio.to_thread(
                run_search_stage,
                aoi_path,
                start,
                end,
                sensor,
                out_dir,
                config.max_results,
                True,
            )
    except Exception as exc:
        await status.edit_text(f"Ошибка поиска сцен: {exc}")
        return
    finally:
        aoi_path.unlink(missing_ok=True)

    scenes = json.loads(result.scenes_json.read_text(encoding="utf-8"))
    scene_models = [Scene.model_validate(item) for item in scenes]
    await status.edit_text(
        format_scene_table(result.provider, result.sensor, scene_models),
        parse_mode=ParseMode.HTML,
    )
    await message.reply_text(
        "Сохранено:\n"
        f"scenes: <code>{html.escape(str(result.scenes_json))}</code>\n"
        f"assets: <code>{html.escape(str(result.asset_manifest or 'disabled'))}</code>",
        parse_mode=ParseMode.HTML,
    )


async def dates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    async with get_semaphore():
        await scene_dates_command(update, context, get_config())


async def bboxdates_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    async with get_semaphore():
        await scene_bbox_dates_command(update, context, get_config())


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    await scene_image_command(update, context, get_config())


async def scene_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await require_authorized(update):
        return
    await scene_image_callback(update, context, get_config())


def build_application() -> Application:
    config = get_config()
    application = Application.builder().token(config.token).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("whoami", whoami_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("bbox", bbox_command))
    application.add_handler(CommandHandler("dates", dates_command))
    application.add_handler(CommandHandler("bboxdates", bboxdates_command))
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(CallbackQueryHandler(scene_callback, pattern=f"^{CALLBACK_PREFIX}:"))
    return application


def main() -> None:
    build_application().run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
