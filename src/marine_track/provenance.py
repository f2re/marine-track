from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from marine_track.cache_policy import aoi_hash_from_geojson

SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|credential|authorization|signature|sas|api[_-]?key)", re.IGNORECASE
)
URL_SCHEMES = {"http", "https", "s3", "gs", "az"}


def code_version() -> str:
    explicit = os.getenv("MARINE_TRACK_CODE_VERSION", "").strip()
    if explicit:
        return explicit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        value = result.stdout.strip()
        return value or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def package_version() -> str:
    try:
        return importlib.metadata.version("marine-track")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def sanitize_url(value: str) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if parts.scheme.lower() not in URL_SCHEMES:
        return value
    hostname = parts.hostname or ""
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = hostname + port
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def safe_path_reference(value: str | Path | None, base_dir: str | Path | None = None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if base_dir is not None:
        try:
            return path.resolve().relative_to(Path(base_dir).resolve()).as_posix()
        except (OSError, ValueError):
            pass
    if path.is_absolute():
        return f"<local>/{path.name}"
    return path.as_posix()


def redact_value(value: Any, *, key: str | None = None, base_dir: str | Path | None = None) -> Any:
    if key and SECRET_KEY_PATTERN.search(key):
        return "[redacted]" if value not in (None, "", False) else value
    if isinstance(value, dict):
        return {
            str(item_key): redact_value(item_value, key=str(item_key), base_dir=base_dir)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, base_dir=base_dir) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item, base_dir=base_dir) for item in value]
    if isinstance(value, Path):
        return safe_path_reference(value, base_dir)
    if isinstance(value, str):
        parsed = urlsplit(value)
        if parsed.scheme.lower() in URL_SCHEMES:
            return sanitize_url(value)
        if value.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", value):
            return safe_path_reference(value, base_dir)
    return value


def raster_provenance(path: Path) -> dict[str, Any]:
    try:
        import rasterio
    except ImportError:
        return {"available": False, "reason": "rasterio_not_installed"}
    try:
        with rasterio.open(path) as dataset:
            transform = [float(item) for item in tuple(dataset.transform)[:6]]
            x_size = abs(float(dataset.transform.a))
            y_size = abs(float(dataset.transform.e))
            return {
                "available": True,
                "driver": dataset.driver,
                "width": dataset.width,
                "height": dataset.height,
                "count": dataset.count,
                "dtypes": list(dataset.dtypes),
                "crs": str(dataset.crs) if dataset.crs else None,
                "transform": transform,
                "pixel_size_x": x_size,
                "pixel_size_y": y_size,
                "nodata": dataset.nodata,
            }
    except Exception as exc:  # noqa: BLE001 - provenance must not break the detection run
        return {"available": False, "reason": type(exc).__name__}


def infer_asset_domain(materialized: Any) -> dict[str, Any]:
    scene = materialized.scene
    metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
    raster_key = str(materialized.raster_key)
    suffix = Path(str(materialized.raster_href).split("?", 1)[0]).suffix.lower()
    media_type = "image/tiff; application=geotiff" if suffix in {".tif", ".tiff"} else None
    units = _first_present(metadata, "units", "unit", "radiometric_units", "measurement_units")
    collection = _first_present(metadata, "collection", "collection_id", "stac_collection")
    processing_level = _first_present(metadata, "processing_level", "product_type", "level")
    return {
        "collection": collection,
        "processing_level": processing_level,
        "asset_key": raster_key,
        "media_type": media_type,
        "units": units,
        "polarizations": list(scene.polarizations or []),
        "band_or_polarization": raster_key,
        "href": sanitize_url(str(materialized.raster_href)),
        "auth_mode": _auth_mode(materialized.provider, str(materialized.raster_href)),
    }


def build_reproducibility_manifest(
    materialized: Any,
    effective_config: Any,
    *,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "code": {
            "commit": code_version(),
            "package_version": package_version(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "effective_processing": effective_config.as_report_dict(),
        "scene": {
            "provider": materialized.provider,
            "sensor": materialized.scene.sensor.value,
            "product_id": materialized.scene.product_id,
            "acquisition_time": materialized.scene.acquisition_time.isoformat(),
            "asset": infer_asset_domain(materialized),
        },
        "raster": raster_provenance(materialized.raster_path),
        "aoi": {
            "hash": aoi_hash_from_geojson(materialized.aoi_geojson),
            "cropped": bool(materialized.cropped),
        },
        "runtime": {
            "raster_cache_hit": bool(materialized.cache_hit),
            "raster_reference": safe_path_reference(materialized.raster_path, output_dir),
        },
    }


def write_redacted_json(path: Path, payload: dict[str, Any], *, base_dir: Path) -> Path:
    sanitized = redact_value(payload, base_dir=base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _auth_mode(provider: str, href: str) -> str:
    if urlsplit(href).query:
        return "signed_url_redacted"
    if provider == "planetary_computer":
        return "runtime_signing"
    if provider in {"copernicus_cdse", "sentinelhub"}:
        return "provider_auth_or_public_asset"
    return "public_or_local"
