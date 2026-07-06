from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from marine_track.cache_policy import raster_cache_path, touch_cache_file
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
    aoi_geojson: dict[str, object] | None = None
    cropped: bool = False
    cache_hit: bool = False


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
    provider = str(record.get("provider") or scene.provider)
    aoi_geojson = record.get("aoi_geojson") if isinstance(record.get("aoi_geojson"), dict) else None
    signed_href = sign_href_if_needed(raster_href, provider)
    suffix = suffix_from_href(raster_href)
    if cache_dir is None:
        target_path = raster_cache_path(
            provider=provider,
            product_id=scene.product_id,
            asset_key=raster_key,
            href=raster_href,
            aoi_geojson=aoi_geojson,
            suffix=suffix,
        )
        work_dir = target_path.parent
    else:
        work_dir = cache_dir / token
        target_path = work_dir / f"{safe_filename(raster_key)}_{short_hash(raster_href)}{suffix}"
    raster_path, cropped, cache_hit = materialize_asset(signed_href, target_path, aoi_geojson)
    return MaterializedScene(
        token=token,
        scene=scene,
        provider=provider,
        sensor=str(record.get("sensor") or scene.sensor.value),
        work_dir=work_dir,
        raster_key=raster_key,
        raster_href=raster_href,
        raster_path=raster_path,
        aoi_geojson=aoi_geojson,
        cropped=cropped,
        cache_hit=cache_hit,
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


def sign_href_if_needed(href: str, provider: str) -> str:
    if provider != "planetary_computer":
        return href
    try:
        import planetary_computer
    except ImportError:
        return href
    return str(planetary_computer.sign_url(href))


def materialize_asset(
    href: str,
    target: Path,
    aoi_geojson: dict[str, object] | None = None,
) -> tuple[Path, bool, bool]:
    suffix = suffix_from_href(href)
    if suffix in ARCHIVE_EXTENSIONS:
        raise MaterializationError(f"Archive assets are not supported yet: {href}")
    if suffix not in RASTER_EXTENSIONS:
        raise MaterializationError(f"Asset is not a GeoTIFF/COG: {href}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        touch_cache_file(target)
        return target, aoi_geojson is not None, True
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    if aoi_geojson is not None:
        crop_raster_to_aoi(href, tmp, aoi_geojson)
        tmp.replace(target)
        return target, True, False
    if href.startswith(("http://", "https://")):
        download_url(href, tmp)
        tmp.replace(target)
        return target, False, False
    source = Path(href)
    if source.is_file():
        tmp.write_bytes(source.read_bytes())
        tmp.replace(target)
        return target, False, False
    raise MaterializationError(f"Asset path is not readable: {href}")


def crop_raster_to_aoi(href: str, target: Path, aoi_geojson: dict[str, object]) -> None:
    try:
        import rasterio
        from rasterio.mask import mask
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MaterializationError("rasterio is required for AOI crop") from exc

    try:
        with rasterio.open(href) as dataset:
            geometries = extract_geometries(aoi_geojson, target_crs=dataset.crs)
            if not geometries:
                raise MaterializationError("AOI GeoJSON does not contain geometries")
            data, transform = mask(dataset, geometries, crop=True, filled=True)
            profile = dataset.profile.copy()
            profile.update(
                driver="GTiff",
                height=data.shape[1],
                width=data.shape[2],
                transform=transform,
                count=data.shape[0],
                compress="deflate",
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.pop("tiled", None)
            with rasterio.open(target, "w", **profile) as output:
                output.write(data)
    except MaterializationError:
        raise
    except Exception as exc:
        raise MaterializationError(f"Failed to crop raster to AOI: {exc}") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise MaterializationError("AOI crop produced empty raster")


def extract_geometries(
    aoi_geojson: dict[str, object],
    target_crs: object | None = None,
) -> list[dict[str, object]]:
    geometries = raw_geometries(aoi_geojson)
    if not geometries:
        return []
    return transform_geometries_to_crs(geometries, target_crs)


def raw_geometries(aoi_geojson: dict[str, object]) -> list[dict[str, object]]:
    geo_type = aoi_geojson.get("type")
    if geo_type == "FeatureCollection":
        features = aoi_geojson.get("features") or []
        return [feature["geometry"] for feature in features if isinstance(feature, dict) and feature.get("geometry")]
    if geo_type == "Feature":
        geometry = aoi_geojson.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    if isinstance(geo_type, str):
        return [aoi_geojson]
    return []


def transform_geometries_to_crs(
    geometries: list[dict[str, object]],
    target_crs: object | None,
) -> list[dict[str, object]]:
    if target_crs is None:
        return geometries
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import mapping, shape
        from shapely.ops import transform
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MaterializationError("pyproj and shapely are required for AOI reprojection") from exc

    dst_crs = CRS.from_user_input(target_crs)
    if dst_crs.to_epsg() == 4326:
        return geometries
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    return [mapping(transform(transformer.transform, shape(geometry))) for geometry in geometries]


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
