from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from marine_track.estimation import LonLat


@dataclass(frozen=True)
class RasterGeoContext:
    transform: Any
    crs: Any


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
