from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from marine_track.estimation import LonLat, haversine_distance_m


@dataclass(frozen=True)
class RasterGeoContext:
    transform: Any
    crs: Any


@dataclass(frozen=True)
class PixelScale:
    x_m: float
    y_m: float
    mean_m: float
    area_m2: float


def pixel_to_lonlat(row: float, col: float, context: RasterGeoContext) -> LonLat:
    """Convert fractional pixel row/col to lon/lat using raster transform and CRS."""
    try:
        from pyproj import CRS, Transformer
        from rasterio.transform import xy
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio and pyproj are required for geospatial conversion") from exc

    x, y = xy(context.transform, row, col, offset="center")
    source_crs = CRS.from_user_input(context.crs)
    if source_crs.to_epsg() == 4326:
        return LonLat(lon=float(x), lat=float(y))

    transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    lon, lat = transformer.transform(x, y)
    return LonLat(lon=float(lon), lat=float(lat))


def lonlat_to_pixel(lon: float, lat: float, transform: Any, crs: Any) -> tuple[float, float]:
    """Convert lon/lat to fractional raster row/col."""
    try:
        from pyproj import CRS, Transformer
        from rasterio.transform import rowcol
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio and pyproj are required for geospatial conversion") from exc

    target_crs = CRS.from_user_input(crs)
    if target_crs.to_epsg() == 4326:
        x, y = lon, lat
    else:
        transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
        x, y = transformer.transform(lon, lat)
    row, col = rowcol(transform, x, y, op=float)
    return float(row), float(col)


def pixel_scale_m(row: float, col: float, context: RasterGeoContext) -> PixelScale:
    center = pixel_to_lonlat(row, col, context)
    right = pixel_to_lonlat(row, col + 1.0, context)
    down = pixel_to_lonlat(row + 1.0, col, context)
    x_m = haversine_distance_m(center, right)
    y_m = haversine_distance_m(center, down)
    mean = (x_m + y_m) / 2.0
    return PixelScale(x_m=x_m, y_m=y_m, mean_m=mean, area_m2=x_m * y_m)
