from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import Geod
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, shape
from shapely.ops import unary_union

DEFAULT_MAX_AOI_AREA_KM2 = 25_000.0
DEFAULT_MAX_AOI_VERTICES = 5_000
DEFAULT_MAX_RASTER_PIXELS = 2_000_000_000
DEFAULT_MAX_TILES = 20_000
DEFAULT_MAX_CANDIDATES = 10_000


class ResourceLimitError(ValueError):
    """Raised before an operation would exceed configured resource limits."""


@dataclass(frozen=True)
class ResourceLimits:
    max_aoi_area_km2: float = DEFAULT_MAX_AOI_AREA_KM2
    max_aoi_vertices: int = DEFAULT_MAX_AOI_VERTICES
    max_raster_pixels: int = DEFAULT_MAX_RASTER_PIXELS
    max_tiles: int = DEFAULT_MAX_TILES
    max_candidates: int = DEFAULT_MAX_CANDIDATES


@dataclass(frozen=True)
class AOIMetrics:
    area_km2: float
    vertex_count: int
    geometry_count: int


def load_resource_limits() -> ResourceLimits:
    return ResourceLimits(
        max_aoi_area_km2=_env_float(
            "MARINE_TRACK_MAX_AOI_AREA_KM2",
            DEFAULT_MAX_AOI_AREA_KM2,
            minimum=0.001,
        ),
        max_aoi_vertices=_env_int(
            "MARINE_TRACK_MAX_AOI_VERTICES",
            DEFAULT_MAX_AOI_VERTICES,
            minimum=4,
        ),
        max_raster_pixels=_env_int(
            "MARINE_TRACK_MAX_RASTER_PIXELS",
            DEFAULT_MAX_RASTER_PIXELS,
            minimum=1,
        ),
        max_tiles=_env_int("MARINE_TRACK_MAX_TILES", DEFAULT_MAX_TILES, minimum=1),
        max_candidates=_env_int(
            "MARINE_TRACK_MAX_CANDIDATES",
            DEFAULT_MAX_CANDIDATES,
            minimum=1,
        ),
    )


def validate_aoi_path(
    path: str | Path,
    limits: ResourceLimits | None = None,
) -> AOIMetrics:
    resolved = Path(path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ResourceLimitError(f"AOI GeoJSON not found: {resolved}") from exc
    except json.JSONDecodeError as exc:
        raise ResourceLimitError(f"AOI GeoJSON is invalid JSON: {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResourceLimitError(f"AOI GeoJSON must be an object: {resolved}")
    return validate_geojson_payload(payload, limits=limits)


def validate_geojson_payload(
    payload: dict[str, Any],
    limits: ResourceLimits | None = None,
) -> AOIMetrics:
    effective = limits or load_resource_limits()
    geometries = _extract_geometries(payload)
    if not geometries:
        raise ResourceLimitError("AOI GeoJSON does not contain any geometry")

    coordinate_pairs = [
        pair for geometry in geometries for pair in _iter_coordinate_pairs(geometry)
    ]
    if not coordinate_pairs:
        raise ResourceLimitError("AOI GeoJSON has no coordinate pairs")
    for longitude, latitude in coordinate_pairs:
        if not math.isfinite(longitude) or not math.isfinite(latitude):
            raise ResourceLimitError("AOI contains non-finite coordinates")
        if not -180.0 <= longitude <= 180.0 or not -90.0 <= latitude <= 90.0:
            raise ResourceLimitError(
                f"AOI coordinate outside WGS84 bounds: {longitude}, {latitude}"
            )
    vertex_count = len(coordinate_pairs)
    if vertex_count > effective.max_aoi_vertices:
        raise ResourceLimitError(
            f"AOI has {vertex_count} vertices; configured limit is "
            f"{effective.max_aoi_vertices}"
        )

    parsed = []
    for raw in geometries:
        try:
            geometry = shape(raw)
        except Exception as exc:  # noqa: BLE001 - convert parser errors to a domain error
            raise ResourceLimitError(f"AOI geometry is invalid: {exc}") from exc
        if geometry.is_empty:
            continue
        if not geometry.is_valid:
            raise ResourceLimitError("AOI geometry is topologically invalid")
        parsed.append(geometry)
    if not parsed:
        raise ResourceLimitError("AOI geometry is empty")

    merged = unary_union(parsed)
    area_km2 = _geodesic_area_m2(merged) / 1_000_000.0
    if not math.isfinite(area_km2) or area_km2 <= 0.0:
        raise ResourceLimitError("AOI has zero or non-finite geodesic area")
    if area_km2 > effective.max_aoi_area_km2:
        raise ResourceLimitError(
            f"AOI area {area_km2:.1f} km² exceeds configured limit "
            f"{effective.max_aoi_area_km2:.1f} km²"
        )

    return AOIMetrics(
        area_km2=area_km2,
        vertex_count=vertex_count,
        geometry_count=len(parsed),
    )


def validate_raster_workload(
    width: int,
    height: int,
    tile_size_px: int,
    tile_overlap_px: int,
    limits: ResourceLimits | None = None,
) -> tuple[int, int]:
    effective = limits or load_resource_limits()
    if width <= 0 or height <= 0:
        raise ResourceLimitError(f"Raster dimensions must be positive, got {width}x{height}")
    pixel_count = int(width) * int(height)
    if pixel_count > effective.max_raster_pixels:
        raise ResourceLimitError(
            f"Raster contains {pixel_count} pixels; configured limit is "
            f"{effective.max_raster_pixels}"
        )
    tile_count = estimated_tile_count(
        width,
        height,
        tile_size_px=tile_size_px,
        tile_overlap_px=tile_overlap_px,
    )
    if tile_count > effective.max_tiles:
        raise ResourceLimitError(
            f"Raster requires {tile_count} tiles; configured limit is "
            f"{effective.max_tiles}"
        )
    return pixel_count, tile_count


def estimated_tile_count(
    width: int,
    height: int,
    *,
    tile_size_px: int,
    tile_overlap_px: int,
) -> int:
    if tile_size_px <= 0:
        raise ValueError("tile_size_px must be positive")
    if tile_overlap_px < 0 or tile_overlap_px >= tile_size_px:
        raise ValueError("tile_overlap_px must be in [0, tile_size_px)")
    step = tile_size_px - tile_overlap_px
    columns = 1 if width <= tile_size_px else math.ceil((width - tile_size_px) / step) + 1
    rows = 1 if height <= tile_size_px else math.ceil((height - tile_size_px) / step) + 1
    return int(rows * columns)


def _extract_geometries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    geo_type = payload.get("type")
    if geo_type == "FeatureCollection":
        output: list[dict[str, Any]] = []
        features = payload.get("features")
        if not isinstance(features, list):
            return []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            if isinstance(geometry, dict):
                output.append(geometry)
        return output
    if geo_type == "Feature":
        geometry = payload.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    return [payload] if isinstance(geo_type, str) else []


def _iter_coordinate_pairs(value: Any):
    if isinstance(value, dict):
        coordinates = value.get("coordinates")
        if coordinates is not None:
            yield from _iter_coordinate_pairs(coordinates)
        geometries = value.get("geometries")
        if isinstance(geometries, list):
            for geometry in geometries:
                yield from _iter_coordinate_pairs(geometry)
        return
    if not isinstance(value, list):
        return
    if (
        len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
        return
    for item in value:
        yield from _iter_coordinate_pairs(item)


_GEOD = Geod(ellps="WGS84")


def _geodesic_area_m2(geometry: Any) -> float:
    if isinstance(geometry, Polygon):
        area, _ = _GEOD.geometry_area_perimeter(geometry)
        return abs(float(area))
    if isinstance(geometry, MultiPolygon):
        return sum(_geodesic_area_m2(item) for item in geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return sum(_geodesic_area_m2(item) for item in geometry.geoms)
    raise ResourceLimitError(
        f"AOI geometry must be polygonal, got "
        f"{getattr(geometry, 'geom_type', type(geometry).__name__)}"
    )


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResourceLimitError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ResourceLimitError(f"{name} must be >= {minimum}, got {value}")
    return value


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ResourceLimitError(f"{name} must be numeric, got {raw!r}") from exc
    if not math.isfinite(value) or value < minimum:
        raise ResourceLimitError(f"{name} must be finite and >= {minimum}, got {value}")
    return value
