from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from marine_track.models import Scene

ASSET_MANIFEST_FIELDS = [
    "scene_id",
    "provider",
    "sensor",
    "acquisition_time",
    "asset_key",
    "href",
    "local_path",
]


@dataclass(frozen=True)
class AssetRecord:
    scene_id: str
    provider: str
    sensor: str
    acquisition_time: str
    asset_key: str
    href: str
    local_path: str | None = None


def safe_filename(value: str, max_len: int = 120) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:max_len - 11]}_{digest}"


def extension_from_href(href: str, default: str = ".bin") -> str:
    parsed = urlparse(href)
    name = Path(parsed.path).name
    suffixes = "".join(Path(name).suffixes)
    return suffixes or default


def iter_asset_records(scenes: list[Scene]) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    for scene in scenes:
        hrefs = scene.assets or ({"product": scene.download_url} if scene.download_url else {})
        for key, href in hrefs.items():
            if not href:
                continue
            records.append(
                AssetRecord(
                    scene_id=scene.product_id,
                    provider=scene.provider,
                    sensor=scene.sensor.value,
                    acquisition_time=scene.acquisition_time.isoformat(),
                    asset_key=key,
                    href=href,
                )
            )
    return records


def write_asset_manifest(scenes: list[Scene], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    records = iter_asset_records(scenes)
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ASSET_MANIFEST_FIELDS)
        writer.writeheader()
        for record in records:
            writer.writerow(record.__dict__)
    return p


def write_scenes_json(scenes: list[Scene], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = [scene.model_dump(mode="json") for scene in scenes]
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def planned_asset_path(record: AssetRecord, cache_dir: str | Path) -> Path:
    scene_dir = Path(cache_dir) / safe_filename(record.scene_id)
    return scene_dir / f"{safe_filename(record.asset_key)}{extension_from_href(record.href)}"


def download_asset(record: AssetRecord, cache_dir: str | Path, overwrite: bool = False) -> Path:
    """Download a public asset URL into the local cache.

    Authentication-specific providers should wrap/sign URLs before calling this function.
    The MVP keeps this routine deliberately small and auditable.
    """
    target = planned_asset_path(record, cache_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target

    request = Request(record.href, headers={"User-Agent": "marine-track-mvp/0.1"})
    with urlopen(request, timeout=120) as response, target.open("wb") as f:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
    return target
