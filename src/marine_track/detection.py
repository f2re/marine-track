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
    training_count_px: int = 0
    training_fraction: float = 0.0
    edge_flag: bool = False
    threshold_value: float | None = None


@dataclass(frozen=True)
class CFARStatistics:
    mask: np.ndarray
    background_mean: np.ndarray
    background_std: np.ndarray
    threshold: np.ndarray
    training_count: np.ndarray
    training_fraction: np.ndarray
    edge: np.ndarray
    training_window_px: int
    guard_window_px: int


def adaptive_threshold_candidates(
    image: np.ndarray,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 0,
    guard_window_px: int = 0,
    min_contrast_sigma: float = 0.0,
    min_training_fraction: float = 0.5,
) -> list[PixelObject]:
    """Detect bright compact candidates in a normalized 2D raster.

    Local CFAR estimates clutter from the outer training window after removing
    the complete inner guard region (which includes the cell under test). NaN
    pixels reduce the effective training fraction and are never detections.
    """

    if image.ndim != 2:
        raise ValueError("image must be 2D")
    finite = np.isfinite(image)
    if not finite.any():
        return []

    statistics = cfar_statistics(
        image,
        threshold_sigma=threshold_sigma,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_training_fraction=min_training_fraction,
    )
    labels, count = ndi.label(statistics.mask)
    objects = ndi.find_objects(labels)
    candidates: list[PixelObject] = []
    for label_id in range(1, count + 1):
        slices = objects[label_id - 1]
        if slices is None:
            continue
        component = labels[slices] == label_id
        area = int(component.sum())
        if not (min_area_px <= area <= max_area_px):
            continue

        local_values = np.where(component, image[slices], -np.inf)
        peak_local_y, peak_local_x = np.unravel_index(
            int(np.nanargmax(local_values)),
            local_values.shape,
        )
        y0, x0 = slices[0].start, slices[1].start
        y1, x1 = slices[0].stop, slices[1].stop
        peak_y = y0 + int(peak_local_y)
        peak_x = x0 + int(peak_local_x)

        cy, cx = ndi.center_of_mass(component)
        values = image[slices][component]
        score = float(np.nanmean(values))
        peak_score = float(np.nanmax(values))
        background_mean = float(statistics.background_mean[peak_y, peak_x])
        background_std = float(statistics.background_std[peak_y, peak_x])
        threshold_value = float(statistics.threshold[peak_y, peak_x])
        training_count_px = int(round(float(statistics.training_count[peak_y, peak_x])))
        training_fraction = float(statistics.training_fraction[peak_y, peak_x])
        edge_flag = bool(statistics.edge[peak_y, peak_x])

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
                training_count_px=training_count_px,
                training_fraction=training_fraction,
                edge_flag=edge_flag,
                threshold_value=threshold_value,
            )
        )
    return candidates


def cfar_statistics(
    image: np.ndarray,
    threshold_sigma: float,
    local_window_px: int = 0,
    guard_window_px: int = 0,
    min_training_fraction: float = 0.5,
) -> CFARStatistics:
    if image.ndim != 2:
        raise ValueError("image must be 2D")
    if threshold_sigma <= 0:
        raise ValueError("threshold_sigma must be positive")
    if not 0.0 <= min_training_fraction <= 1.0:
        raise ValueError("min_training_fraction must be in [0, 1]")

    finite = np.isfinite(image)
    shape = image.shape
    if local_window_px <= 0:
        values = image[finite].astype("float64")
        mean_value = float(values.mean()) if values.size else 0.0
        std_value = float(values.std()) if values.size else 0.0
        threshold_value = mean_value + threshold_sigma * std_value
        background_mean = np.full(shape, mean_value, dtype="float32")
        background_std = np.full(shape, std_value, dtype="float32")
        threshold = np.full(shape, threshold_value, dtype="float32")
        training_count = np.full(shape, float(values.size), dtype="float32")
        training_fraction = np.where(finite, 1.0, 0.0).astype("float32")
        edge = ~finite
        mask = finite & (image > threshold_value)
        return CFARStatistics(
            mask=mask,
            background_mean=background_mean,
            background_std=background_std,
            threshold=threshold,
            training_count=training_count,
            training_fraction=training_fraction,
            edge=edge,
            training_window_px=0,
            guard_window_px=0,
        )

    window = _odd_window(local_window_px, minimum=3)
    guard = _odd_window(max(guard_window_px, 1), minimum=1)
    if guard >= window:
        raise ValueError("guard_window_px must be smaller than local_window_px")

    safe = np.where(finite, image, 0.0).astype("float64")
    weights = finite.astype("float64")
    outer_area = float(window * window)
    guard_area = float(guard * guard)

    outer_count = _window_sum(weights, window)
    outer_sum = _window_sum(safe, window)
    outer_squared = _window_sum(safe * safe, window)
    guard_count = _window_sum(weights, guard)
    guard_sum = _window_sum(safe, guard)
    guard_squared = _window_sum(safe * safe, guard)

    training_count = np.maximum(outer_count - guard_count, 0.0)
    training_sum = outer_sum - guard_sum
    training_squared = outer_squared - guard_squared
    expected_count = max(1.0, outer_area - guard_area)

    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.divide(
            training_sum,
            training_count,
            out=np.zeros_like(training_sum),
            where=training_count > 0,
        )
        mean_squared = np.divide(
            training_squared,
            training_count,
            out=np.zeros_like(training_squared),
            where=training_count > 0,
        )
    variance = np.maximum(mean_squared - mean * mean, 0.0)
    std = np.sqrt(variance)
    threshold = mean + threshold_sigma * std
    training_fraction = np.clip(training_count / expected_count, 0.0, 1.0)
    edge = training_fraction < (1.0 - 1e-6)
    mask = (
        finite
        & (training_fraction >= min_training_fraction)
        & (training_count > 0)
        & (image > threshold)
    )

    return CFARStatistics(
        mask=mask,
        background_mean=mean.astype("float32"),
        background_std=std.astype("float32"),
        threshold=threshold.astype("float32"),
        training_count=training_count.astype("float32"),
        training_fraction=training_fraction.astype("float32"),
        edge=edge,
        training_window_px=window,
        guard_window_px=guard,
    )


def cfar_mask(
    image: np.ndarray,
    threshold_sigma: float,
    local_window_px: int = 0,
    guard_window_px: int = 0,
    min_training_fraction: float = 0.5,
) -> np.ndarray:
    """Compatibility wrapper returning only the CFAR detection mask."""

    return cfar_statistics(
        image,
        threshold_sigma=threshold_sigma,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_training_fraction=min_training_fraction,
    ).mask


def _window_sum(values: np.ndarray, size: int) -> np.ndarray:
    return ndi.uniform_filter(
        values,
        size=size,
        mode="constant",
        cval=0.0,
    ) * float(size * size)


def _odd_window(value: int, *, minimum: int) -> int:
    size = max(minimum, int(value))
    if size % 2 == 0:
        size += 1
    return size


def local_background_stats(
    image: np.ndarray,
    component: np.ndarray,
    y0: int,
    x0: int,
    y1: int,
    x1: int,
    local_window_px: int,
) -> tuple[float, float]:
    """Legacy component-level background statistic helper."""

    margin = max(8, int(local_window_px or 31) // 2)
    yy0 = max(0, y0 - margin)
    xx0 = max(0, x0 - margin)
    yy1 = min(image.shape[0], y1 + margin)
    xx1 = min(image.shape[1], x1 + margin)
    patch = image[yy0:yy1, xx0:xx1]
    exclude = np.zeros(patch.shape, dtype=bool)
    rel_y0 = y0 - yy0
    rel_x0 = x0 - xx0
    exclude[
        rel_y0 : rel_y0 + component.shape[0],
        rel_x0 : rel_x0 + component.shape[1],
    ] = component
    background = patch[np.isfinite(patch) & ~exclude]
    if background.size == 0:
        finite_values = image[np.isfinite(image)]
        if finite_values.size == 0:
            return 0.0, 0.0
        return float(np.nanmean(finite_values)), float(np.nanstd(finite_values))
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
