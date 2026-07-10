from __future__ import annotations

import asyncio
import hashlib
import html
import json
import math
import threading
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
from marine_track.telegram_ui import ACTION_MENU, MENU_CALLBACK_PREFIX
from marine_track.telegram_user_state import save_last_bbox

DEFAULT_HOURS = 12
CALLBACK_PREFIX = "mtimg"
DETECT_CALLBACK_PREFIX = "mtdetect"
PAGE_CALLBACK_PREFIX = "mtpg"
SCENE_PAGE_SIZE = 6
REGISTRY_FILE = "scene_registry.json"
_REGISTRY_LOCK = threading.Lock()
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
    owner_user_id: int
    owner_chat_id: int
    provider: str
    sensor: str
    scene: dict[str, object]
    scenes_json: str
    asset_manifest: str | None
    created_at: str
    aoi_geojson: dict[str, object] | None = None
    search_hours: int | None = None


@dataclass(frozen=True)
class ScenePage:
    provider: str
    sensor: Sensor
    tokens: list[str]
    scenes: list[Scene]
    page: int
    page_count: int
    hours: int | None = None
    cache_hit: bool | None = None


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


def effective_user_id(update: Update) -> int:
    return int(getattr(update.effective_user, "id", 0) or 0)


def effective_chat_id(update: Update) -> int:
    return int(getattr(update.effective_chat, "id", 0) or 0)


def scene_token(scene: Scene, owner_user_id: int, owner_chat_id: int) -> str:
    raw = (
        f"{owner_user_id}|{owner_chat_id}|{scene.provider}|{scene.sensor.value}|"
        f"{scene.product_id}|{scene.acquisition_time.isoformat()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


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
    path = registry_path(output_dir)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def register_scenes(
    output_dir: Path,
    provider: str,
    sensor: Sensor,
    scenes: list[Scene],
    scenes_json: Path,
    asset_manifest: Path | None,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    aoi_geojson: dict[str, object] | None = None,
    search_hours: int | None = None,
) -> list[str]:
    if owner_user_id <= 0 or owner_chat_id == 0:
        raise ValueError("Telegram scene registry requires non-zero owner user/chat ids")
    tokens: list[str] = []
    created_at = datetime.now(timezone.utc).isoformat()
    with _REGISTRY_LOCK:
        registry = load_registry(output_dir)
        for scene in scenes:
            token = scene_token(scene, owner_user_id, owner_chat_id)
            record = SceneRegistryRecord(
                token=token,
                owner_user_id=owner_user_id,
                owner_chat_id=owner_chat_id,
                provider=provider,
                sensor=sensor.value,
                scene=scene.model_dump(mode="json"),
                scenes_json=str(scenes_json),
                asset_manifest=str(asset_manifest) if asset_manifest else None,
                created_at=created_at,
                aoi_geojson=aoi_geojson,
                search_hours=search_hours,
            )
            registry[token] = record.__dict__
            tokens.append(token)
        save_registry(output_dir, registry)
    return tokens


def find_scene(
    output_dir: Path,
    token: str,
    *,
    owner_user_id: int,
    owner_chat_id: int,
) -> tuple[Scene, dict[str, object]] | None:
    record = load_registry(output_dir).get(token)
    if not isinstance(record, dict):
        return None
    if record.get("owner_user_id") != owner_user_id or record.get("owner_chat_id") != owner_chat_id:
        return None
    scene_payload = record.get("scene")
    if not isinstance(scene_payload, dict):
        return None
    return Scene.model_validate(scene_payload), record


def read_geojson(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"AOI GeoJSON must be an object: {path}")
    return payload


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
    with NamedTemporaryFile("w", suffix=".geojson", prefix="marine_track_bbox_", delete=False) as tmp:
        json.dump(payload, tmp)
        return Path(tmp.name)


def run_dir(base_dir: Path, prefix: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base_dir / f"{prefix}_{stamp}"


def load_scenes(path: Path) -> list[Scene]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [Scene.model_validate(item) for item in payload]


def page_count(total: int, page_size: int = SCENE_PAGE_SIZE) -> int:
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    return max(1, math.ceil(total / page_size))


def clamp_page(page: int, total: int, page_size: int = SCENE_PAGE_SIZE) -> int:
    return min(max(page, 0), page_count(total, page_size) - 1)


def scene_page_slice(
    tokens: list[str],
    scenes: list[Scene],
    page: int = 0,
    page_size: int = SCENE_PAGE_SIZE,
) -> tuple[list[str], list[Scene], int, int]:
    if len(tokens) != len(scenes):
        raise ValueError("tokens and scenes length mismatch")
    current_page = clamp_page(page, len(scenes), page_size)
    start = current_page * page_size
    end = start + page_size
    return tokens[start:end], scenes[start:end], current_page, page_count(len(scenes), page_size)


def scene_page_callback_data(token: str, page: int) -> str:
    return f"{PAGE_CALLBACK_PREFIX}:{token}:{page}"


def scene_keyboard(
    tokens: list[str],
    scenes: list[Scene],
    page: int = 0,
    page_size: int = SCENE_PAGE_SIZE,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    page_tokens, page_scenes, current_page, total_pages = scene_page_slice(tokens, scenes, page, page_size)
    for token, scene in zip(page_tokens, page_scenes, strict=True):
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
    if total_pages > 1 and tokens:
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton("◀️ Назад", callback_data=scene_page_callback_data(tokens[0], current_page - 1))
            )
        nav_row.append(
            InlineKeyboardButton(
                f"стр. {current_page + 1}/{total_pages}",
                callback_data=scene_page_callback_data(tokens[0], current_page),
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton("▶️ Далее", callback_data=scene_page_callback_data(tokens[0], current_page + 1))
            )
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}")])
    return InlineKeyboardMarkup(rows)


def format_scenes_message(
    provider: str,
    sensor: Sensor,
    scenes: list[Scene],
    hours: int | None,
    cache_hit: bool | None = None,
    page: int = 0,
    page_size: int = SCENE_PAGE_SIZE,
) -> str:
    current_page = clamp_page(page, len(scenes), page_size)
    total_pages = page_count(len(scenes), page_size)
    start = current_page * page_size
    page_scenes = scenes[start : start + page_size]
    title = (
        f"Снимки за последние {hours} ч · стр. {current_page + 1}/{total_pages}"
        if hours is not None
        else f"Снимки из сохраненного поиска · стр. {current_page + 1}/{total_pages}"
    )
    lines = [
        f"<b>{title}</b>",
        f"provider: <code>{html.escape(provider)}</code>",
        f"sensor: <code>{sensor.value}</code>",
        f"count: <code>{len(scenes)}</code>",
    ]
    if cache_hit is not None:
        cache_status = "hit" if cache_hit else "refresh"
        lines.append(f"search_cache: <code>{cache_status}</code>")
    lines.append("")
    for offset, scene in enumerate(page_scenes, start=1):
        index = start + offset
        time_text = html.escape(scene.acquisition_time.strftime("%Y-%m-%d %H:%MZ"))
        product = html.escape(scene.product_id[:72])
        lines.append(f"{index}. <code>{time_text}</code> · {html.escape(scene.sensor.value)} · {html.escape(scene.provider)}")
        lines.append(
            "   "
            f"beam={html.escape(scene.beam_mode or '-')} · "
            f"pol/cloud={html.escape(scene.polarization_label())} · "
            f"product=<code>{product}</code>"
        )
    lines.append("")
    lines.append("Нажмите 📷 для preview или 🔎 для запуска детекции по сроку.")
    return "\n".join(lines)


def restore_scene_page(
    output_dir: Path,
    token: str,
    page: int,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    page_size: int = SCENE_PAGE_SIZE,
) -> ScenePage:
    registry = load_registry(output_dir)
    record = registry.get(token)
    if not isinstance(record, dict):
        raise FileNotFoundError("token not found in scene registry")
    if record.get("owner_user_id") != owner_user_id or record.get("owner_chat_id") != owner_chat_id:
        raise FileNotFoundError("token not found in scene registry")
    scenes_json = record.get("scenes_json")
    if not isinstance(scenes_json, str):
        raise FileNotFoundError("scenes_json not found in scene registry")
    scenes_path = Path(scenes_json)
    if not scenes_path.is_file():
        raise FileNotFoundError(scenes_json)
    scenes = load_scenes(scenes_path)
    tokens = [scene_token(scene, owner_user_id, owner_chat_id) for scene in scenes]
    sensor_value = str(record.get("sensor") or (scenes[0].sensor.value if scenes else Sensor.AUTO.value))
    provider = str(record.get("provider") or (scenes[0].provider if scenes else "-"))
    hours_raw = record.get("search_hours")
    try:
        hours = int(hours_raw) if hours_raw is not None else None
    except (TypeError, ValueError):
        hours = None
    try:
        sensor = Sensor(sensor_value)
    except ValueError:
        sensor = scenes[0].sensor if scenes else Sensor.AUTO
    return ScenePage(
        provider=provider,
        sensor=sensor,
        tokens=tokens,
        scenes=scenes,
        page=clamp_page(page, len(scenes), page_size),
        page_count=page_count(len(scenes), page_size),
        hours=hours,
    )


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

    aoi_geojson = read_geojson(config.default_aoi)
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
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
        aoi_geojson=aoi_geojson,
        search_hours=hours,
    )
    if not scenes:
        await status.edit_text(f"За последние {hours} ч снимков не найдено.")
        return
    await status.edit_text(
        format_scenes_message(result.provider, result.sensor, scenes, hours, cache_hit=result.cache_hit),
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
        aoi_geojson = bbox_geojson(west, south, east, north)
        aoi_path = write_temp_aoi(aoi_geojson)
        save_last_bbox(config.output_dir, effective_user_id(update), sensor, west, south, east, north, hours)
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
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
        aoi_geojson=aoi_geojson,
        search_hours=hours,
    )
    if not scenes:
        await status.edit_text(f"За последние {hours} ч снимков не найдено.")
        return
    await status.edit_text(
        format_scenes_message(result.provider, result.sensor, scenes, hours, cache_hit=result.cache_hit),
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

    found = find_scene(
        config.output_dir,
        token,
        owner_user_id=effective_user_id(update),
        owner_chat_id=effective_chat_id(update),
    )
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


async def scene_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, config: TelegramBotConfig) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    parts = query.data.split(":")
    if len(parts) != 3 or parts[0] != PAGE_CALLBACK_PREFIX:
        return
    token = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        page = 0
    try:
        scene_page = restore_scene_page(
            config.output_dir,
            token,
            page,
            owner_user_id=effective_user_id(update),
            owner_chat_id=effective_chat_id(update),
        )
    except Exception:
        if query.message:
            await query.message.reply_text(
                "Список сцен устарел, выполните /dates или /bboxdates заново.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 Меню", callback_data=f"{MENU_CALLBACK_PREFIX}:{ACTION_MENU}")]]
                ),
            )
        return
    if not query.message:
        return
    await query.message.edit_text(
        format_scenes_message(
            scene_page.provider,
            scene_page.sensor,
            scene_page.scenes,
            scene_page.hours,
            page=scene_page.page,
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=scene_keyboard(scene_page.tokens, scene_page.scenes, page=scene_page.page),
    )
