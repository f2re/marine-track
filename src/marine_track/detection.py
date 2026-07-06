from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi


@dataclass(frozen=True)
class PixelObject:
    label: int
    centroid_yx: tuple[float, float]
    area_px: int
    bbox_yx: tuple[int, int, int, int]
    score: float


def adaptive_threshold_candidates(
    image: np.ndarray,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 0,
    guard_window_px: int = 0,
) -> list[PixelObject]:
    """Detect bright compact candidates in a 2D raster.

    If `local_window_px` is greater than zero, a simple local-CFAR style detector is
    used: pixels must exceed local mean + N * local std. Otherwise the legacy global
    mean/std threshold is used. Shoreline/land masks are handled upstream by setting
    masked pixels to NaN.
    """
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    if not finite.any():
        return []

    mask = cfar_mask(image, threshold_sigma, local_window_px, guard_window_px)
    labels, n = ndi.label(mask)
    objects = ndi.find_objects(labels)
    candidates: list[PixelObject] = []
    for label_id in range(1, n + 1):
        slc = objects[label_id - 1]
        if slc is None:
            continue
        component = labels[slc] == label_id
        area = int(component.sum())
        if not (min_area_px <= area <= max_area_px):
            continue
        cy, cx = ndi.center_of_mass(component)
        y0, x0 = slc[0].start, slc[1].start
        y1, x1 = slc[0].stop
        x1 = slc[1].stop
        score = float(np.nanmean(image[slc][component]))
        candidates.append(
            PixelObject(
                label=label_id,
                centroid_yx=(float(y0 + cy), float(x0 + cx)),
                area_px=area,
                bbox_yx=(y0, x0, y1, x1),
                score=score,
            )
        )
    return candidates


def cfar_mask(
    image: np.ndarray,
    threshold_sigma: float,
    local_window_px: int = 0,
    guard_window_px: int = 0,
) -> np.ndarray:
    finite = np.isfinite(image)
    if local_window_px <= 0:
        values = image[finite]
        threshold = float(values.mean() + threshold_sigma * values.std())
        mask = np.zeros_like(image, dtype=bool)
        mask[finite] = image[finite] > threshold
        return mask

    window = max(3, int(local_window_px))
    if window % 2 == 0:
        window += 1
    safe = np.where(finite, image, 0.0).astype("float64")
    weights = finite.astype("float64")
    count = ndi.uniform_filter(weights, size=window, mode="constant")
    summed = ndi.uniform_filter(safe, size=window, mode="constant")
    squared = ndi.uniform_filter(safe * safe, size=window, mode="constant")
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.divide(summed, count, out=np.zeros_like(summed), where=count > 0)
        mean2 = np.divide(squared, count, out=np.zeros_like(squared), where=count > 0)
    variance = np.maximum(mean2 - mean * mean, 0.0)
    std = np.sqrt(variance)
    threshold = mean + threshold_sigma * std
    mask = finite & (image > threshold) & (count > 0.25)

    guard = int(guard_window_px)
    if guard > 0:
        if guard % 2 == 0:
            guard += 1
        local_max = ndi.maximum_filter(np.where(finite, image, -np.inf), size=guard, mode="nearest")
        mask &= image >= local_max
    return mask
