from __future__ import annotations

import hashlib
import json
import os
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from marine_track.models import Scene, Sensor

DEFAULT_CACHE_DIR = "runs/cache"


@dataclass(frozen=True)
class CleanupReport:
    removed_files: int
    removed_dirs: int
    removed_bytes: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cache_root() -> Path:
    return Path(os.getenv("MARINE_TRACK_CACHE_DIR", DEFAULT_CACHE_DIR))


def scene_search_cache_dir() -> Path:
    return Path(os.getenv("MARINE_TRACK_SCENE_SEARCH_CACHE_DIR") or cache_root() / "scene_search")


def raster_cache_dir() -> Path:
    return Path(os.getenv("MARINE_TRACK_RASTER_CACHE_DIR") or cache_root() / "rasters")


def scene_search_ttl_seconds() -> int:
    return int(os.getenv("MARINE_TRACK_SCENE_SEARCH_TTL_MIN", "30")) * 60


def retention_seconds(env_name: str, default_days: int) -> int:
    return int(float(os.getenv(env_name, str(default_days))) * 86400)


def aoi_hash_from_path(path: Path) -> str:
    return short_hash(path.read_bytes())


def aoi_hash_from_geojson(value: dict[str, object] | None) -> str:
    if value is None:
        return "no-aoi"
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return short_hash(payload)


def search_cache_key(
    aoi_path: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    max_results: int,
) -> str:
    duration_minutes = max(1, int((end - start).total_seconds() // 60))
    payload = {
        "aoi_hash": aoi_hash_from_path(aoi_path),
        "sensor": sensor.value,
        "duration_minutes": duration_minutes,
        "max_results": max_results,
    }
    return short_hash(json.dumps(payload, sort_keys=True).encode("utf-8"), length=20)


def search_cache_path(cache_key: str) -> Path:
    return scene_search_cache_dir() / f"{cache_key}.json"


def read_scene_search_cache(path: Path) -> tuple[str, Sensor, list[Scene]] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
        if (utc_now() - created_at).total_seconds() > scene_search_ttl_seconds():
            return None
        provider = str(payload["provider"])
        sensor = Sensor(str(payload["sensor"]))
        scenes = [Scene.model_validate(item) for item in payload.get("scenes", [])]
        if not scenes:
            return None
        return provider, sensor, scenes
    except Exception:
        return None


def write_scene_search_cache(path: Path, provider: str, sensor: Sensor, scenes: list[Scene]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": utc_now().isoformat(),
        "ttl_seconds": scene_search_ttl_seconds(),
        "provider": provider,
        "sensor": sensor.value,
        "scenes": [scene.model_dump(mode="json") for scene in scenes],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def raster_cache_path(
    provider: str,
    product_id: str,
    asset_key: str,
    href: str,
    aoi_geojson: dict[str, object] | None,
    suffix: str,
) -> Path:
    payload = {
        "provider": provider,
        "product_id": product_id,
        "asset_key": asset_key,
        "href": href.split("?", 1)[0],
        "aoi_hash": aoi_hash_from_geojson(aoi_geojson),
    }
    key = short_hash(json.dumps(payload, sort_keys=True).encode("utf-8"), length=24)
    name = safe_filename(f"{provider}_{asset_key}_{key}") + suffix
    return raster_cache_dir() / safe_filename(product_id, max_len=90) / name


def touch_cache_file(path: Path) -> None:
    with suppress(Exception):
        path.touch(exist_ok=True)


def cleanup_path(path: Path, max_age_seconds: int) -> CleanupReport:
    if not path.exists():
        return CleanupReport(removed_files=0, removed_dirs=0, removed_bytes=0)
    cutoff = utc_now().timestamp() - max_age_seconds
    removed_files = 0
    removed_dirs = 0
    removed_bytes = 0
    for item in sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if item.is_file():
            try:
                if item.stat().st_mtime >= cutoff:
                    continue
                size = item.stat().st_size
                item.unlink()
                removed_files += 1
                removed_bytes += size
            except FileNotFoundError:
                continue
        elif item.is_dir():
            try:
                item.rmdir()
                removed_dirs += 1
            except OSError:
                continue
    return CleanupReport(removed_files=removed_files, removed_dirs=removed_dirs, removed_bytes=removed_bytes)


def cleanup_runtime(output_dir: Path | None = None, cache_dir: Path | None = None) -> dict[str, CleanupReport]:
    cache = cache_dir or cache_root()
    outputs = output_dir or Path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"))
    return {
        "scene_search_cache": cleanup_path(scene_search_cache_dir(), retention_seconds("MARINE_TRACK_SCENE_SEARCH_CACHE_RETENTION_DAYS", 7)),
        "raster_cache": cleanup_path(raster_cache_dir(), retention_seconds("MARINE_TRACK_RASTER_CACHE_RETENTION_DAYS", 14)),
        "mask_cache": cleanup_path(cache / "masks", retention_seconds("MARINE_TRACK_MASK_CACHE_RETENTION_DAYS", 90)),
        "detections": cleanup_path(outputs / "detections", retention_seconds("MARINE_TRACK_DETECTION_OUTPUT_RETENTION_DAYS", 7)),
        "runs": cleanup_path(outputs / "runs", retention_seconds("MARINE_TRACK_RUN_OUTPUT_RETENTION_DAYS", 7)),
    }


def remove_empty_dir(path: Path) -> None:
    with suppress(OSError):
        path.rmdir()


def short_hash(data: bytes, length: int = 16) -> str:
    return hashlib.sha256(data).hexdigest()[:length]


def safe_filename(value: str, max_len: int = 120) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    if len(cleaned) <= max_len:
        return cleaned or "cache"
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:max_len - 11]}_{digest}"
