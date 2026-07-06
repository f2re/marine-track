from __future__ import annotations

import asyncio
import hashlib
import html
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from marine_track.models import Scene, Sensor
from marine_track.pipeline import run_search_stage
from marine_track.telegram_config import TelegramBotConfig

DEFAULT_HOURS = 12
CALLBACK_PREFIX = "mtimg"
DETECT_CALLBACK_PREFIX = "mtdetect"
REGISTRY_FILE = "scene_registry.json"
PREVIEW_KEYS = (
    "thumbnail",
    "rendered_preview",
    "overview",
    "preview",
    "quicklook",
    "browse",
    "visual",
    "visual_10m",
    "true_color",
    "image",
)
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
DOCUMENT_EXTENSIONS = PHOTO_EXTENSIONS | {".tif", ".tiff"}


@dataclass(frozen=True)
class SceneRegistryRecord:
    token: str
    provider: str
    sensor: str
    scene: dict[str, object]
    scenes_json: str
    asset_manifest: str | None
    created_at: str


def parse_scene_hours(value: str | None, default: int = DEFAULT_HOURS) -> int:
    if not value:
        return default
    try:
        hours = int(value)
    except ValueError as exc:
        raise ValueError("hours должен быть целым числом") from exc
    if hours <= 0 or hours > 24 * 30:
        raise ValueError("hours должен быть в диапазоне 1..720")
    return hours


def parse_scene_sensor(value: str | None, default: Sensor) -> Sensor:
    if not value:
        return default
    normalized = value.strip().lower()
    aliases = {"s1": "sentinel1", "sar": "sentinel1", "s2": "sentinel2", "optical": "sentinel2"}
    normalized = aliases.get(normalized, normalized)
    try:
        return Sensor(normalized)
    except ValueError as exc:
        raise ValueError("sensor должен быть auto, sentinel1 или sentinel2") from exc


def utc_window(hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(hours=hours), end


def scene_token(scene: Scene) -> str:
    raw = f"{scene.provider}|{scene.sensor.value}|{scene.product_id}|{scene.acquisition_time.isoformat()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def registry_path(output_dir: Path) -> Path:
    return output_dir / REGISTRY_FILE


def load_registry(output_dir: Path) -> dict[str, dict[str, object]]:
    path = registry_path(output_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_registry(output_dir: Path, registry: dict[str, dict[str, object]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_path(output_dir).write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def register_scenes(
    output_dir: Path,
    provider: str,
    sensor: Sensor,
    scenes: list[Scene],
    scenes_json: Path,
    asset_manifest: Path | None,
) -> list[str]:
    registry = load_registry(output_dir)
    tokens: list[str] = []
    created_at = datetime.now(timezone.utc).isoformat()
    for scene in scenes:
        token = scene_token(scene)
        record = SceneRegistryRecord(
            token=token,
            provider=provider,
            sensor=sensor.value,
            scene=scene.model_dump(mode="json"),
            scenes_json=str(scenes_json),
            asset_manifest=str(asset_manifest) if asset_manifest else None,
            created_at=created_at,
        )
        registry[token] = record.__dict__
        tokens.append(token)
    save_registry(output_dir, registry)
    return tokens


def find_scene(output_dir: Path, token: str) -> tuple[Scene, dict[str, object]] | None:
    record = load_registry(output_dir).get(token)
    if not isinstance(record, dict):
        return None
    scene_payload = record.get("scene")
    if not isinstance(scene_payload, dict):
        return None
    return Scene.model_validate(scene_payload), record


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


def run_dir(base_dir: Path, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base_dir / f"{prefix}_{stamp}"


def load_scenes(path: Path) -> list[Scene]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Scene.model_validate(item) for item in payload]


def scene_keyboard(tokens: list[str], scenes: list[Scene], max_buttons: int = 12) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for token, scene in list(zip(tokens, scenes, strict=True))[:max_buttons]:
        time_label = scene.acquisition_time.strftime("%m-%d %H:%MZ")
        sensor_label = scene.sensor.value.replace("sentinel", "S")
        rows.append(
            [
                InlineKeyboardButton(
                    f"📷 {time_label} {sensor_label}",
                    callback_data=f"{CALLBACK_PREFIX}:{token}",
                ),
                InlineKeyboardButton("🔎 Детекция", callback_data=f"{DETECT_CALLBACK_PREFIX}:{token}"),
            ]
        )
    return InlineKeyboardMarkup(rows)


def format_scenes_message(provider: str, sensor: Sensor, scenes: list[Scene], hours: int) -> str:
    lines = [
        f"<b>Доступные снимки за последние {hours} ч</b>",
        f"provider: <code>{html.escape(provider)}</code>",
        f"sensor: <code>{sensor.value}</code>",
        f"count: <code>{len(scenes)}</code>",
        "",
    ]
    for index, scene in enumerate(scenes[:12], start=1):
        time_text = html.escape(scene.acquisition_time.isoformat())
        product = html.escape(scene.product_id[:80])
        lines.append(f"{index}. <code>{time_text}</code>")
        lines.append(f"   <code>{product}</code>")
        lines.append(f"   beam={html.escape(scene.beam_mode or '-')} pol/cloud={html.escape(scene.polarization_label())}")
    if len(scenes) > 12:
        lines.append(f"... ещё {len(scenes) - 12}")
    lines.append("")
    lines.append("Нажмите 📷 для preview или 🔎 для запуска детекции по сроку.")
    return "\n".join(lines)


def select_preview_asset(scene: Scene) -> tuple[str, str] | None:
    lowered = {key.lower(): (key, href) for key, href in scene.assets.items() if href}
    for wanted in PREVIEW_KEYS:
        if wanted in lowered:
            return lowered[wanted]
    for key, href in scene.assets.items():
        parsed = urlparse(href)
        suffix = Path(parsed.path).suffix.lower()
        if suffix in DOCUMENT_EXTENSIONS:
            return key, href
    return None


def file_extension_from_url(url: str, default: str = ".jpg") -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in DOCUMENT_EXTENSIONS:
        return suffix
    return default


def download_preview(url: str, target_dir: Path, token: str) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = file_extension_from_url(url)
    target = target_dir / f"{token}{suffix}"
    if target.is_file() and target.stat().st_size > 0:
        return target
    request = Request(url, headers={"User-Agent": "marine-track-bot/0.1"})
    with urlopen(request, timeout=90) as response, target.open("wb") as file_obj:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    if target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError("preview asset downloaded as empty file")
    return target


def scene_caption(scene: Scene, token: str, asset_key: str) -> str:
    return (
        f"{scene.sensor.value} / {scene.provider}\n"
        f"{scene.acquisition_time.isoformat()}\n"
        f"asset: {asset_key}\n"
        f"token: {token}\n"
        f"{scene.product_id[:120]}"
    )


async def list_dates_command(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    try:
        sensor = parse_scene_sensor(args[0] if args else None, config.default_sensor)
        hours = parse_scene_hours(args[1] if len(args) > 1 else None, DEFAULT_HOURS)
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}\nПример: /dates sentinel1 12")
        return
    if not config.default_aoi.is_file():
        await message.reply_text(f"AOI не найден: {config.default_aoi}")
        return

    start, end = utc_window(hours)
    out_dir = run_dir(config.output_dir, "dates")
    status = await message.reply_text(f"⏳ Ищу снимки за последние {hours} ч: {sensor.value}")
    try:
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
        await status.edit_text(f"Ошибка поиска снимков: {exc}")
        return

    scenes = load_scenes(result.scenes_json)
    tokens = register_scenes(
        config.output_dir,
        result.provider,
        result.sensor,
        scenes,
        result.scenes_json,
        result.asset_manifest,
    )
    if not scenes:
        await status.edit_text(f"За последние {hours} ч снимков не найдено.")
        return
    await status.edit_text(
        format_scenes_message(result.provider, result.sensor, scenes, hours),
        parse_mode=ParseMode.HTML,
        reply_markup=scene_keyboard(tokens, scenes),
    )


async def bbox_dates_command(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if len(args) < 5:
        await message.reply_text(
            "Формат: /bboxdates [auto|sentinel1|sentinel2] west south east north [hours]\n"
            "Пример: /bboxdates sentinel1 36.5 43.8 38.5 45.0 12"
        )
        return
    try:
        sensor = parse_scene_sensor(args[0], config.default_sensor)
        west, south, east, north = [float(value) for value in args[1:5]]
        hours = parse_scene_hours(args[5] if len(args) > 5 else None, DEFAULT_HOURS)
        aoi_path = write_temp_aoi(bbox_geojson(west, south, east, north))
    except ValueError as exc:
        await message.reply_text(f"Ошибка: {exc}")
        return

    start, end = utc_window(hours)
    out_dir = run_dir(config.output_dir, "bboxdates")
    status = await message.reply_text(
        f"⏳ Ищу снимки за последние {hours} ч: {sensor.value}, bbox={west},{south},{east},{north}"
    )
    try:
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
        await status.edit_text(f"Ошибка поиска снимков: {exc}")
        return
    finally:
        aoi_path.unlink(missing_ok=True)

    scenes = load_scenes(result.scenes_json)
    tokens = register_scenes(
        config.output_dir,
        result.provider,
        result.sensor,
        scenes,
        result.scenes_json,
        result.asset_manifest,
    )
    if not scenes:
        await status.edit_text(f"За последние {hours} ч снимков не найдено.")
        return
    await status.edit_text(
        format_scenes_message(result.provider, result.sensor, scenes, hours),
        parse_mode=ParseMode.HTML,
        reply_markup=scene_keyboard(tokens, scenes),
    )


async def send_scene_preview_by_token(update: Update, token: str, config: TelegramBotConfig) -> None:
    target = update.effective_message
    query = update.callback_query
    if query:
        await query.answer()
    if not target and query:
        target = query.message
    if not target:
        return

    found = find_scene(config.output_dir, token)
    if not found:
        await target.reply_text("Снимок не найден в локальном registry. Выполните /dates или /bboxdates заново.")
        return
    scene, _record = found
    preview = select_preview_asset(scene)
    if preview is None:
        assets = "\n".join(f"- {key}" for key in sorted(scene.assets)) or "assets отсутствуют"
        await target.reply_text(
            "Для этой сцены нет preview/quicklook asset. Доступные assets:\n" + assets
        )
        return

    asset_key, href = preview
    status = await target.reply_text(f"⏳ Загружаю preview: {asset_key}")
    try:
        path = await asyncio.to_thread(download_preview, href, config.output_dir / "previews", token)
    except Exception as exc:
        await status.edit_text(f"Не удалось загрузить preview asset {asset_key}: {exc}\nURL: {href}")
        return

    caption = scene_caption(scene, token, asset_key)
    suffix = path.suffix.lower()
    try:
        if suffix in PHOTO_EXTENSIONS:
            with path.open("rb") as file_obj:
                await target.reply_photo(photo=file_obj, caption=caption)
        else:
            with path.open("rb") as file_obj:
                await target.reply_document(document=file_obj, caption=caption)
        await status.delete()
    except Exception as exc:
        await status.edit_text(f"Preview скачан, но Telegram не принял файл: {exc}\nfile={path}")


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    message = update.effective_message
    if not message:
        return
    args = list(context.args or [])
    if not args:
        await message.reply_text("Формат: /image <token>. Token берется из кнопок /dates или /bboxdates.")
        return
    await send_scene_preview_by_token(update, args[0].strip(), config)


async def image_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    prefix, _, token = query.data.partition(":")
    if prefix != CALLBACK_PREFIX or not token:
        return
    await send_scene_preview_by_token(update, token, config)
