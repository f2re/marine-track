from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from marine_track.models import Scene
from marine_track.telegram_scene_browser import find_scene

RASTER_EXTENSIONS = {".tif", ".tiff"}
ARCHIVE_EXTENSIONS = {".zip", ".safe"}
PREVIEW_KEY_HINTS = (
    "thumbnail",
    "preview",
    "quicklook",
    "browse",
    "overview",
    "rendered_preview",
)
S1_PRIORITY_HINTS = ("vv", "sigma0_vv", "gamma0_vv", "rtc", "vh", "sigma0_vh")
S2_PRIORITY_HINTS = ("visual", "true_color", "b08", "b04", "b03", "b02")
GENERIC_PRIORITY_HINTS = ("cog", "geotiff", "tif", "data", "asset")


@dataclass(frozen=True)
class MaterializedScene:
    token: str
    scene: Scene
    provider: str
    sensor: str
    work_dir: Path
    raster_key: str
    raster_href: str
    raster_path: Path


class MaterializationError(RuntimeError):
    pass


def materialize_scene_from_token(
    token: str,
    output_dir: Path,
    cache_dir: Path | None = None,
) -> MaterializedScene:
    found = find_scene(output_dir, token)
    if found is None:
        raise MaterializationError(f"Scene token not found: {token}")
    scene, record = found
    selected = select_processing_asset(scene)
    if selected is None:
        keys = ", ".join(sorted(scene.assets)) or "no assets"
        raise MaterializationError(
            "No processable GeoTIFF/COG asset found for scene. "
            "Preview assets are not used for detection. "
            f"Available assets: {keys}"
        )
    raster_key, raster_href = selected
    work_dir = (cache_dir or output_dir / "materialized") / token
    raster_path = materialize_asset(raster_href, work_dir, raster_key)
    return MaterializedScene(
        token=token,
        scene=scene,
        provider=str(record.get("provider") or scene.provider),
        sensor=str(record.get("sensor") or scene.sensor.value),
        work_dir=work_dir,
        raster_key=raster_key,
        raster_href=raster_href,
        raster_path=raster_path,
    )


def select_processing_asset(scene: Scene) -> tuple[str, str] | None:
    candidates = [(key, href) for key, href in scene.assets.items() if is_raster_href(href)]
    candidates = [item for item in candidates if not is_preview_key(item[0])]
    if not candidates:
        return None
    priority = asset_priority_hints(scene)
    return sorted(candidates, key=lambda item: asset_score(item[0], item[1], priority))[0]


def asset_priority_hints(scene: Scene) -> tuple[str, ...]:
    if scene.sensor.value == "sentinel1":
        return S1_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    if scene.sensor.value == "sentinel2":
        return S2_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    return GENERIC_PRIORITY_HINTS


def asset_score(key: str, href: str, priority: tuple[str, ...]) -> tuple[int, str]:
    haystack = f"{key} {href}".lower()
    for index, hint in enumerate(priority):
        if hint in haystack:
            return index, key
    return len(priority), key


def is_preview_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in PREVIEW_KEY_HINTS)


def is_raster_href(href: str) -> bool:
    suffix = suffix_from_href(href)
    return suffix in RASTER_EXTENSIONS


def suffix_from_href(href: str) -> str:
    parsed = urlparse(href)
    return Path(parsed.path).suffix.lower()


def materialize_asset(href: str, work_dir: Path, key: str) -> Path:
    suffix = suffix_from_href(href)
    if suffix in ARCHIVE_EXTENSIONS:
        raise MaterializationError(f"Archive assets are not supported yet: {href}")
    if suffix not in RASTER_EXTENSIONS:
        raise MaterializationError(f"Asset is not a GeoTIFF/COG: {href}")
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"{safe_filename(key)}_{short_hash(href)}{suffix}"
    if target.is_file() and target.stat().st_size > 0:
        return target
    if href.startswith(("http://", "https://")):
        download_url(href, target)
        return target
    source = Path(href)
    if source.is_file():
        target.write_bytes(source.read_bytes())
        return target
    raise MaterializationError(f"Asset path is not readable: {href}")


def download_url(url: str, target: Path) -> None:
    request = Request(url, headers={"User-Agent": "marine-track-detect/0.1"})
    with urlopen(request, timeout=300) as response, target.open("wb") as file_obj:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise MaterializationError(f"Downloaded empty asset: {url}")


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned[:80] or "asset"


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
