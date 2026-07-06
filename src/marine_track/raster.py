from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class Tile:
    data: np.ndarray
    row_start: int
    col_start: int

    @property
    def row_stop(self) -> int:
        return self.row_start + self.data.shape[0]

    @property
    def col_stop(self) -> int:
        return self.col_start + self.data.shape[1]


def read_raster_band(path: str | Path, band: int = 1) -> np.ndarray:
    """Read one raster band as float32 and convert nodata to NaN."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for raster reading") from exc

    with rasterio.open(path) as dataset:
        data = dataset.read(band).astype("float32")
        nodata = dataset.nodata
    if nodata is not None:
        data[data == nodata] = np.nan
    return data


def percentile_normalize(
    image: np.ndarray,
    lower: float = 2.0,
    upper: float = 98.0,
) -> np.ndarray:
    """Normalize image into 0..1 using finite-value percentiles."""
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    out = np.full(image.shape, np.nan, dtype="float32")
    if not finite.any():
        return out

    lo, hi = np.nanpercentile(image[finite], [lower, upper])
    if hi <= lo:
        lo = float(np.nanmin(image[finite]))
        hi = float(np.nanmax(image[finite]))
        if hi <= lo:
            out[finite] = 0.0
            return out
    out[finite] = np.clip((image[finite] - lo) / (hi - lo), 0.0, 1.0)
    return out


def iter_tiles(image: np.ndarray, tile_size: int, overlap: int = 0) -> Iterator[Tile]:
    """Yield 2D tiles with optional overlap.

    Edge starts are snapped to the final full tile origin where possible, so the
    iterator covers the full image without producing tiny duplicate edge tiles.
    """
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    if tile_size <= 0:
        raise ValueError("tile_size must be positive")
    if overlap < 0 or overlap >= tile_size:
        raise ValueError("overlap must be in [0, tile_size)")

    rows, cols = image.shape
    for row in _tile_starts(rows, tile_size, tile_size - overlap):
        for col in _tile_starts(cols, tile_size, tile_size - overlap):
            yield Tile(
                data=image[row : min(row + tile_size, rows), col : min(col + tile_size, cols)],
                row_start=row,
                col_start=col,
            )


def _tile_starts(length: int, tile_size: int, step: int) -> list[int]:
    if length <= tile_size:
        return [0]
    last = length - tile_size
    starts = list(range(0, last + 1, step))
    if starts[-1] != last:
        starts.append(last)
    return starts


def finite_fraction(image: np.ndarray) -> float:
    if image.size == 0:
        return 0.0
    return float(np.isfinite(image).sum() / image.size)
