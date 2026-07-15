from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from marine_track.cache_policy import raster_cache_path, touch_cache_file
from marine_track.models import Scene, SceneAsset
from marine_track.provider_auth import bearer_headers, cdse_access_token, sentinelhub_access_token
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
# Co-polarized VV is the operational single-band baseline. Keep the generic RTC
# hint after VV: both dual-pol assets contain ``rtc`` in their URL, and placing it
# first makes VH/VV tie and accidentally selects VH by lexical key order.
S1_PRIORITY_HINTS = ("gamma0_vv", "sigma0_vv", "vv", "rtc", "gamma0_vh", "sigma0_vh", "vh")
S2_PRIORITY_HINTS = ("b08", "b04", "b03", "b02", "visual", "true_color")
GENERIC_PRIORITY_HINTS = ("cog", "geotiff", "tif", "data", "analytic", "asset")
TIFF_MEDIA_HINTS = ("image/tiff", "geotiff", "cloud-optimized")


@dataclass(frozen=True)
class AssetProbe:
    ok: bool
    status: int | None
    content_type: str | None
    bytes_checked: int
    range_supported: bool | None


@dataclass(frozen=True)
class MaterializedScene:
    token: str
    scene: Scene
    provider: str
    sensor: str
    work_dir: Path
    raster_key: str
    raster_href: str
    raster_asset: SceneAsset
    raster_path: Path
    aoi_geojson: dict[str, object] | None = None
    cropped: bool = False
    cache_hit: bool = False
    asset_probe: AssetProbe | None = None


class MaterializationError(RuntimeError):
    pass


def materialize_scene_from_token(
    token: str,
    output_dir: Path,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    cache_dir: Path | None = None,
) -> MaterializedScene:
    found = find_scene(
        output_dir,
        token,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )
    if found is None:
        raise MaterializationError(f"Scene token not found or not owned by caller: {token}")
    scene, record = found
    selected = select_processing_asset_record(scene)
    if selected is None:
        keys = ", ".join(sorted(scene.assets)) or "no assets"
        raise MaterializationError(
            "No processable GeoTIFF/COG asset found for scene. "
            "Preview, XML and archive assets are not used for detection. "
            f"Available assets: {keys}"
        )
    raster_key, raster_asset, raster_href = selected
    provider = str(record.get("provider") or scene.provider)
    aoi_geojson = record.get("aoi_geojson") if isinstance(record.get("aoi_geojson"), dict) else None
    access_href, headers = prepare_asset_access(raster_href, provider, raster_asset)
    suffix = suffix_from_asset(raster_asset, raster_href)
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
    raster_path, cropped, cache_hit, probe = materialize_asset(
        access_href,
        target_path,
        aoi_geojson,
        headers=headers,
        return_probe=True,
    )
    return MaterializedScene(
        token=token,
        scene=scene,
        provider=provider,
        sensor=str(record.get("sensor") or scene.sensor.value),
        work_dir=work_dir,
        raster_key=raster_key,
        raster_href=raster_href,
        raster_asset=raster_asset,
        raster_path=raster_path,
        aoi_geojson=aoi_geojson,
        cropped=cropped,
        cache_hit=cache_hit,
        asset_probe=probe,
    )


def select_processing_asset(scene: Scene) -> tuple[str, str] | None:
    """Compatibility wrapper returning key/href for search capability checks."""

    selected = select_processing_asset_record(scene)
    if selected is None:
        return None
    key, _asset, href = selected
    return key, href


def select_processing_asset_record(scene: Scene) -> tuple[str, SceneAsset, str] | None:
    candidates: list[tuple[str, SceneAsset, str]] = []
    for key in scene.assets:
        asset = scene.asset_record(key)
        if asset is None or is_preview_asset(key, asset) or not is_raster_asset(asset):
            continue
        href = asset.preferred_href(prefer_https=scene.provider == "copernicus_cdse")
        candidates.append((key, asset, href))
    if not candidates:
        return None
    priority = asset_priority_hints(scene)
    return sorted(
        candidates,
        key=lambda item: asset_score(item[0], item[1], item[2], priority, scene.provider),
    )[0]


def asset_priority_hints(scene: Scene) -> tuple[str, ...]:
    if scene.sensor.value == "sentinel1":
        return S1_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    if scene.sensor.value == "sentinel2":
        return S2_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    return GENERIC_PRIORITY_HINTS


def asset_score(
    key: str,
    asset: SceneAsset,
    href: str,
    priority: tuple[str, ...],
    provider: str = "",
) -> tuple[int, int, int, int, str]:
    haystack = " ".join(
        [
            key,
            href,
            asset.media_type or "",
            asset.band or "",
            asset.polarization or "",
            " ".join(asset.roles),
        ]
    ).lower()
    semantic = next((index for index, hint in enumerate(priority) if hint in haystack), len(priority))
    role_penalty = 0 if any(role.lower() in {"data", "analytic", "backscatter"} for role in asset.roles) else 1
    media_penalty = 0 if is_tiff_media(asset.media_type) else 1
    storage_penalty = 0
    if provider == "copernicus_cdse" and href.lower().startswith("s3://"):
        storage_penalty = 3
    return semantic, role_penalty, media_penalty, storage_penalty, key


def is_preview_asset(key: str, asset: SceneAsset) -> bool:
    lowered = key.lower()
    roles = {role.lower() for role in asset.roles}
    return any(hint in lowered for hint in PREVIEW_KEY_HINTS) or bool(
        roles & {"thumbnail", "overview", "preview"}
    )


def is_raster_asset(asset: SceneAsset) -> bool:
    if is_tiff_media(asset.media_type):
        return True
    return any(suffix_from_href(href) in RASTER_EXTENSIONS for _name, href in asset.all_hrefs())


def is_tiff_media(media_type: str | None) -> bool:
    lowered = (media_type or "").lower()
    return any(hint in lowered for hint in TIFF_MEDIA_HINTS)


def prepare_asset_access(
    href: str,
    provider: str,
    asset: SceneAsset,
) -> tuple[str, dict[str, str]]:
    if provider == "planetary_computer" or asset.auth_mode == "runtime_signing":
        return sign_href_if_needed(href, "planetary_computer"), {}
    if provider == "copernicus_cdse" or asset.auth_mode == "bearer":
        token = cdse_access_token() if provider == "copernicus_cdse" else sentinelhub_access_token()
        if token:
            return href, bearer_headers(token)
        if asset.auth_mode == "bearer":
            raise MaterializationError(
                f"Bearer credentials are required for provider={provider}; configure its OAuth client"
            )
    if provider == "sentinelhub":
        token = sentinelhub_access_token()
        if token:
            return href, bearer_headers(token)
    return href, {}


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
    *,
    headers: dict[str, str] | None = None,
    return_probe: bool = False,
) -> tuple[Path, bool, bool] | tuple[Path, bool, bool, AssetProbe]:
    suffix = suffix_from_href(href)
    if suffix in ARCHIVE_EXTENSIONS:
        raise MaterializationError(f"Archive assets are not supported yet: {safe_url(href)}")
    if suffix not in RASTER_EXTENSIONS and not href.startswith(("http://", "https://")):
        raise MaterializationError(f"Asset is not a GeoTIFF/COG: {safe_url(href)}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with materialization_lock(target):
        if target.is_file() and target.stat().st_size > 0:
            try:
                probe = probe_raster_asset(str(target))
            except MaterializationError:
                # A previous process/version may have left a corrupt non-empty cache file.
                # Under the lock it is safe to remove and rebuild it once.
                target.unlink(missing_ok=True)
            else:
                touch_cache_file(target)
                result = (target, aoi_geojson is not None, True)
                return (*result, probe) if return_probe else result

        source_probe = probe_raster_asset(href, headers=headers)
        tmp = target.with_name(
            f".{target.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        tmp.unlink(missing_ok=True)
        try:
            if aoi_geojson is not None:
                crop_raster_to_aoi(href, tmp, aoi_geojson, headers=headers)
                cropped = True
            elif href.startswith(("http://", "https://")):
                download_url(href, tmp, headers=headers)
                cropped = False
            else:
                source = Path(href)
                if not source.is_file():
                    raise MaterializationError(
                        f"Asset path is not readable: {safe_url(href)}"
                    )
                tmp.write_bytes(source.read_bytes())
                cropped = False

            probe_raster_asset(str(tmp))
            tmp.replace(target)
            touch_cache_file(target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        result = (target, cropped, False)
        return (*result, source_probe) if return_probe else result


@contextmanager
def materialization_lock(target: Path, timeout_s: float | None = None):
    """Serialize creation of one cache target across workers and processes."""

    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - production target is Linux
        raise MaterializationError("fcntl is required for raster cache locking") from exc

    if timeout_s is None:
        raw = os.getenv("MARINE_TRACK_RASTER_LOCK_TIMEOUT_S", "300").strip()
        try:
            timeout_s = float(raw)
        except ValueError as exc:
            raise MaterializationError(
                f"MARINE_TRACK_RASTER_LOCK_TIMEOUT_S must be numeric, got {raw!r}"
            ) from exc
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise MaterializationError("raster cache lock timeout must be finite and positive")

    lock_path = target.with_suffix(target.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        try:
            os.chmod(lock_path, 0o600)
            os.utime(lock_path, None)
        except OSError:
            pass
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with suppress(OSError):
                    os.utime(lock_path, None)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise MaterializationError(
                        f"Timed out waiting for raster cache lock: {target.name}"
                    ) from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def probe_raster_asset(
    href: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
    max_bytes: int | None = None,
) -> AssetProbe:
    timeout = timeout or int(os.getenv("MARINE_TRACK_ASSET_PROBE_TIMEOUT_S", "30"))
    max_bytes = max_bytes or int(os.getenv("MARINE_TRACK_ASSET_PROBE_BYTES", "4096"))
    if href.startswith(("http://", "https://")):
        request_headers = {
            "User-Agent": "marine-track-asset-probe/0.1",
            "Range": f"bytes=0-{max_bytes - 1}",
            **(headers or {}),
        }
        request = Request(href, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = response.read(max_bytes)
                status = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type") if response.headers else None
                accept_ranges = response.headers.get("Accept-Ranges") if response.headers else None
        except HTTPError as exc:
            raise MaterializationError(
                f"Raster access probe failed with HTTP {exc.code}: {safe_url(href)}"
            ) from exc
        except (OSError, URLError) as exc:
            raise MaterializationError(
                f"Raster access probe failed ({type(exc).__name__}): {safe_url(href)}"
            ) from exc
        if status not in {200, 206, None}:
            raise MaterializationError(f"Unexpected raster probe status {status}: {safe_url(href)}")
        if not _looks_like_tiff(payload, content_type):
            raise MaterializationError(
                f"Raster probe did not return TIFF bytes/content-type: {safe_url(href)}"
            )
        return AssetProbe(
            ok=True,
            status=status,
            content_type=content_type,
            bytes_checked=len(payload),
            range_supported=status == 206 or (accept_ranges or "").lower() == "bytes",
        )

    source = Path(href)
    if not source.is_file():
        raise MaterializationError(f"Local raster does not exist: {source}")
    payload = source.read_bytes()[:max_bytes]
    if not _looks_like_tiff(payload, None):
        raise MaterializationError(f"Local asset is not a TIFF raster: {source.name}")
    return AssetProbe(True, None, None, len(payload), None)


def crop_raster_to_aoi(
    href: str,
    target: Path,
    aoi_geojson: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    try:
        import numpy as np
        import rasterio
        from rasterio.mask import mask
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MaterializationError("rasterio and numpy are required for AOI crop") from exc

    header_value = _gdal_header_value(headers)
    context = rasterio.Env(GDAL_HTTP_HEADERS=header_value) if header_value else nullcontext()
    try:
        with context, rasterio.open(href) as dataset:
            geometries = extract_geometries(aoi_geojson, target_crs=dataset.crs)
            if not geometries:
                raise MaterializationError("AOI GeoJSON does not contain geometries")
            data, transform = mask(dataset, geometries, crop=True, filled=False)
            mask_array = np.ma.getmaskarray(data)
            valid_mask = ~np.any(mask_array, axis=0)
            filled_data = np.asarray(data.astype("float32").filled(np.nan), dtype="float32")
            if not valid_mask.any():
                raise MaterializationError("AOI crop contains no valid source pixels")

            profile = dataset.profile.copy()
            profile.update(
                driver="GTiff",
                dtype="float32",
                nodata=np.nan,
                height=filled_data.shape[1],
                width=filled_data.shape[2],
                transform=transform,
                count=filled_data.shape[0],
                compress="deflate",
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.pop("tiled", None)
            dataset_tags = dataset.tags()
            band_tags = [dataset.tags(index) for index in range(1, dataset.count + 1)]
            descriptions = tuple(dataset.descriptions)
            scales = tuple(dataset.scales)
            offsets = tuple(dataset.offsets)

            with rasterio.open(target, "w", **profile) as output:
                output.write(filled_data)
                output.write_mask(valid_mask.astype("uint8") * 255)
                if dataset_tags:
                    output.update_tags(**dataset_tags)
                for index, tags in enumerate(band_tags, start=1):
                    if tags:
                        output.update_tags(index, **tags)
                try:
                    output.descriptions = descriptions
                    output.scales = scales
                    output.offsets = offsets
                except (AttributeError, TypeError, ValueError):
                    pass
    except MaterializationError:
        raise
    except Exception as exc:
        raise MaterializationError(f"Failed to crop raster to AOI: {type(exc).__name__}") from exc
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
        return [
            feature["geometry"]
            for feature in features
            if isinstance(feature, dict) and feature.get("geometry")
        ]
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


def download_url(
    url: str,
    target: Path,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    request = Request(
        url,
        headers={"User-Agent": "marine-track-detect/0.1", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=300) as response, target.open("wb") as file_obj:  # noqa: S310
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_obj.write(chunk)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise MaterializationError(
            f"Failed to download raster ({type(exc).__name__}): {safe_url(url)}"
        ) from exc
    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise MaterializationError(f"Downloaded empty asset: {safe_url(url)}")


def suffix_from_asset(asset: SceneAsset, href: str) -> str:
    suffix = suffix_from_href(href)
    if suffix in RASTER_EXTENSIONS:
        return suffix
    if is_tiff_media(asset.media_type):
        return ".tif"
    return suffix or ".tif"


def suffix_from_href(href: str) -> str:
    parsed = urlparse(href)
    return Path(parsed.path).suffix.lower()


def is_preview_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in PREVIEW_KEY_HINTS)


def is_raster_href(href: str) -> bool:
    return suffix_from_href(href) in RASTER_EXTENSIONS


def _looks_like_tiff(payload: bytes, content_type: str | None) -> bool:
    magic = payload[:4]
    if magic in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}:
        return True
    return is_tiff_media(content_type)


def _gdal_header_value(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    return "\n".join(f"{key}: {value}" for key, value in headers.items())


def safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return f"{parsed.scheme}://{parsed.hostname or ''}{parsed.path}"
    return value


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned[:80] or "asset"


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
