from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage as ndi

# Numerical guards only. They prevent a uniform background from producing zero
# or non-finite contrast. These constants are not sensor-noise calibration.
CONTRAST_STD_FLOOR = 1e-6
MAX_CONTRAST_SIGMA = 100.0


@dataclass(frozen=True)
class PixelObject:
    label: int
    centroid_yx: tuple[float, float]
    area_px: int
    bbox_yx: tuple[int, int, int, int]
    score: float
    peak_score: float
    background_mean: float
    background_std: float
    contrast_sigma: float
    major_axis_px: float
    minor_axis_px: float
    orientation_image_deg: float | None
    elongation: float


def adaptive_threshold_candidates(
    image: np.ndarray,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 0,
    guard_window_px: int = 0,
    min_contrast_sigma: float = 0.0,
) -> list[PixelObject]:
    """Detect bright compact candidates in a 2D raster.

    The input image is expected to be normalized to 0..1 upstream. With a positive
    local_window_px this is a local-CFAR style detector: candidate pixels must
    exceed local mean + threshold_sigma * local std. Components then receive
    shape and local-contrast metrics for provenance and ranking.
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
        y1, x1 = slc[0].stop, slc[1].stop
        values = image[slc][component]
        score = float(np.nanmean(values))
        peak_score = float(np.nanmax(values))
        background_mean, background_std = local_background_stats(
            image,
            component,
            y0,
            x0,
            y1,
            x1,
            local_window_px,
        )
        contrast_delta = max(0.0, peak_score - background_mean)
        raw_contrast = contrast_delta / max(background_std, CONTRAST_STD_FLOOR)
        contrast_sigma = float(min(MAX_CONTRAST_SIGMA, raw_contrast))
        if contrast_sigma < float(min_contrast_sigma):
            continue
        major_axis, minor_axis, orientation, elongation = component_shape_metrics(component)
        candidates.append(
            PixelObject(
                label=label_id,
                centroid_yx=(float(y0 + cy), float(x0 + cx)),
                area_px=area,
                bbox_yx=(y0, x0, y1, x1),
                score=score,
                peak_score=peak_score,
                background_mean=background_mean,
                background_std=background_std,
                contrast_sigma=contrast_sigma,
                major_axis_px=major_axis,
                minor_axis_px=minor_axis,
                orientation_image_deg=orientation,
                elongation=elongation,
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
        local_max = ndi.maximum_filter(
            np.where(finite, image, -np.inf),
            size=guard,
            mode="nearest",
        )
        mask &= image >= local_max
    return mask


def local_background_stats(
    image: np.ndarray,
    component: np.ndarray,
    y0: int,
    x0: int,
    y1: int,
    x1: int,
    local_window_px: int,
) -> tuple[float, float]:
    margin = max(8, int(local_window_px or 31) // 2)
    yy0 = max(0, y0 - margin)
    xx0 = max(0, x0 - margin)
    yy1 = min(image.shape[0], y1 + margin)
    xx1 = min(image.shape[1], x1 + margin)
    patch = image[yy0:yy1, xx0:xx1]
    exclude = np.zeros(patch.shape, dtype=bool)
    rel_y0 = y0 - yy0
    rel_x0 = x0 - xx0
    exclude[rel_y0 : rel_y0 + component.shape[0], rel_x0 : rel_x0 + component.shape[1]] = component
    background = patch[np.isfinite(patch) & ~exclude]
    if background.size == 0:
        finite = image[np.isfinite(image)]
        if finite.size == 0:
            return 0.0, 0.0
        return float(np.nanmean(finite)), float(np.nanstd(finite))
    return float(np.nanmean(background)), float(np.nanstd(background))


def component_shape_metrics(component: np.ndarray) -> tuple[float, float, float | None, float]:
    coords = np.argwhere(component)
    if len(coords) <= 1:
        return 1.0, 1.0, None, 1.0
    centered = coords.astype("float64") - coords.astype("float64").mean(axis=0)
    cov = np.cov(centered, rowvar=False)
    try:
        eigvals, eigvecs = np.linalg.eigh(cov)
    except np.linalg.LinAlgError:
        return float(component.shape[0]), float(component.shape[1]), None, 1.0
    order = np.argsort(eigvals)[::-1]
    eigvec_major = eigvecs[:, order[0]]
    projections_major = centered @ eigvec_major
    eigvec_minor = eigvecs[:, order[1]]
    projections_minor = centered @ eigvec_minor
    major_axis = float(projections_major.max() - projections_major.min() + 1.0)
    minor_axis = float(projections_minor.max() - projections_minor.min() + 1.0)
    orientation = math.degrees(math.atan2(float(eigvec_major[0]), float(eigvec_major[1])))
    elongation = major_axis / max(minor_axis, 1e-6)
    return major_axis, minor_axis, orientation, elongation
