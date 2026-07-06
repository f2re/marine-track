from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


class LandMaskError(RuntimeError):
    pass


def apply_land_mask(
    image: np.ndarray,
    transform: Any,
    crs: Any,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float = 0.0,
) -> np.ndarray:
    """Set land/shoreline pixels to NaN using a GeoJSON polygon mask.

    The mask file is expected to be in EPSG:4326 lon/lat coordinates. It is
    reprojected to the raster CRS before rasterization. If the file path is empty,
    the input image is returned unchanged.
    """
    if not land_mask_geojson:
        return image
    path = Path(land_mask_geojson)
    if not path.is_file():
        raise LandMaskError(f"land mask GeoJSON not found: {path}")

    geometries = load_geojson_geometries(path)
    if not geometries:
        raise LandMaskError(f"land mask GeoJSON has no geometries: {path}")

    projected = project_and_buffer_geometries(geometries, crs, shoreline_buffer_m)
    mask = rasterize_geometries(projected, image.shape, transform)
    output = image.copy()
    output[mask] = np.nan
    return output


def load_geojson_geometries(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        return []
    geo_type = payload.get("type")
    if geo_type == "FeatureCollection":
        features = payload.get("features") or []
        return [feature["geometry"] for feature in features if isinstance(feature, dict) and feature.get("geometry")]
    if geo_type == "Feature":
        geometry = payload.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    if isinstance(geo_type, str):
        return [payload]
    return []


def project_and_buffer_geometries(
    geometries: list[dict[str, Any]],
    target_crs: Any,
    shoreline_buffer_m: float,
) -> list[dict[str, Any]]:
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import mapping, shape
        from shapely.ops import transform as shapely_transform
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LandMaskError("pyproj and shapely are required for land mask reprojection") from exc

    dst_crs = CRS.from_user_input(target_crs)
    transformer = None
    if dst_crs.to_epsg() != 4326:
        transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)

    output: list[dict[str, Any]] = []
    for geometry in geometries:
        geom = shape(geometry)
        if transformer is not None:
            geom = shapely_transform(transformer.transform, geom)
        if shoreline_buffer_m > 0:
            geom = geom.buffer(buffer_distance_for_crs(dst_crs, shoreline_buffer_m))
        if not geom.is_empty:
            output.append(mapping(geom))
    return output


def buffer_distance_for_crs(crs: Any, shoreline_buffer_m: float) -> float:
    try:
        from pyproj import CRS
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LandMaskError("pyproj is required for buffer calculation") from exc

    parsed = CRS.from_user_input(crs)
    if parsed.is_geographic:
        return float(shoreline_buffer_m) / 111_320.0
    return float(shoreline_buffer_m)


def rasterize_geometries(
    geometries: list[dict[str, Any]],
    shape: tuple[int, int],
    transform: Any,
) -> np.ndarray:
    try:
        from rasterio.features import rasterize
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise LandMaskError("rasterio is required for land mask rasterization") from exc

    if not geometries:
        return np.zeros(shape, dtype=bool)
    return rasterize(
        [(geometry, 1) for geometry in geometries],
        out_shape=shape,
        transform=transform,
        fill=0,
        all_touched=True,
        dtype="uint8",
    ).astype(bool)
