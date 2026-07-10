from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from marine_track.models import Scene

ASSET_MANIFEST_FIELDS = [
    "scene_id",
    "provider",
    "sensor",
    "acquisition_time",
    "asset_key",
    "href",
    "media_type",
    "roles",
    "band",
    "polarization",
    "units",
    "auth_mode",
    "storage",
    "alternate_hrefs",
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
    media_type: str | None = None
    roles: str = ""
    band: str | None = None
    polarization: str | None = None
    units: str | None = None
    auth_mode: str = "unknown"
    storage: str = "unknown"
    alternate_hrefs: str = "{}"
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
        keys = list(scene.assets)
        if not keys and scene.download_url:
            keys = ["product"]
        for key in keys:
            asset = scene.asset_record(key)
            href = asset.href if asset is not None else scene.download_url
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
                    media_type=asset.media_type if asset else None,
                    roles=",".join(asset.roles) if asset else "",
                    band=asset.band if asset else None,
                    polarization=asset.polarization if asset else None,
                    units=asset.units if asset else None,
                    auth_mode=asset.auth_mode if asset else "unknown",
                    storage=asset.storage if asset else "unknown",
                    alternate_hrefs=json.dumps(
                        {name: sanitize_url(value) for name, value in (asset.alternate_hrefs if asset else {}).items()},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            )
    return records


def write_asset_manifest(scenes: list[Scene], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ASSET_MANIFEST_FIELDS)
        writer.writeheader()
        for record in iter_asset_records(scenes):
            row = dict(record.__dict__)
            row["href"] = sanitize_url(str(row["href"]))
            writer.writerow(row)
    return output


def write_scenes_json(scenes: list[Scene], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [scene.model_dump(mode="json") for scene in scenes]
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return output


def planned_asset_path(record: AssetRecord, cache_dir: str | Path) -> Path:
    scene_dir = Path(cache_dir) / safe_filename(record.scene_id)
    return scene_dir / f"{safe_filename(record.asset_key)}{extension_from_href(record.href)}"


def download_asset(record: AssetRecord, cache_dir: str | Path, overwrite: bool = False) -> Path:
    target = planned_asset_path(record, cache_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target
    request = Request(record.href, headers={"User-Agent": "marine-track-mvp/0.1"})
    with urlopen(request, timeout=120) as response, target.open("wb") as file_obj:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    return target


def sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "s3", "az", "azure", "gs"}:
        return value
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))
