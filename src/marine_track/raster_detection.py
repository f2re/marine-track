from __future__ import annotations

import math
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from marine_track.calibration import load_calibration_profile, score_candidate
from marine_track.calibration_phase2_evaluation import active_post_filter_threshold
from marine_track.detection import PixelObject, adaptive_threshold_candidates
from marine_track.geospatial import RasterGeoContext, pixel_scale_m, pixel_to_lonlat
from marine_track.land_mask import apply_prepared_land_mask, prepare_land_mask
from marine_track.models import VesselDetection
from marine_track.resource_limits import (
    ResourceLimitError,
    ResourceLimits,
    validate_raster_workload,
)

NORMALIZATION_LOW_PERCENTILE = 2.0
NORMALIZATION_HIGH_PERCENTILE = 98.0


def detect_candidates_from_raster(
    path: str | Path,
    satellite: str,
    provider: str,
    product_id: str,
    acquisition_time: datetime,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 31,
    guard_window_px: int = 5,
    min_contrast_sigma: float = 0.0,
    min_training_fraction: float = 0.5,
    tile_size_px: int = 1024,
    tile_overlap_px: int = 128,
    normalization_sample_pixels: int = 1_000_000,
    max_raster_pixels: int = 2_000_000_000,
    max_tiles: int = 20_000,
    max_candidates: int = 10_000,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    calibration_profile: dict[str, Any] | None = None,
    phase2_output_dir: str | Path | None = None,
) -> list[VesselDetection]:
    """Run bounded tiled candidate detection with scene-wide normalization.

    The raster is never read into memory as one full array. A bounded decimated
    sample establishes one scene-wide normalization domain; overlapping tiles are
    then processed with true training-ring CFAR. Ownership boundaries ensure that
    a candidate from an overlap is emitted once.
    """

    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("rasterio is required for raster detection") from exc

    output_dir = Path(
        phase2_output_dir or os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram")
    )
    if calibration_profile is None:
        calibration_profile = load_calibration_profile(output_dir)
    post_filter_threshold, phase2_profile_id = active_post_filter_threshold(output_dir)

    limits = ResourceLimits(
        max_raster_pixels=int(max_raster_pixels),
        max_tiles=int(max_tiles),
        max_candidates=int(max_candidates),
    )
    with rasterio.open(path) as dataset:
        pixel_count, tile_count = validate_raster_workload(
            dataset.width,
            dataset.height,
            tile_size_px,
            tile_overlap_px,
            limits=limits,
        )
        context = RasterGeoContext(transform=dataset.transform, crs=dataset.crs)
        prepared_land = prepare_land_mask(
            land_mask_geojson,
            dataset.crs,
            shoreline_buffer_m,
        )
        normalization_low, normalization_high, sample_count = _normalization_domain(
            dataset,
            prepared_land,
            max_sample_pixels=normalization_sample_pixels,
        )
        windows = list(
            _tile_windows(
                dataset.width,
                dataset.height,
                tile_size_px=tile_size_px,
                tile_overlap_px=tile_overlap_px,
            )
        )
        raw_candidates: list[PixelObject] = []
        candidate_tiles: list[dict[str, int]] = []
        for tile_index, (row0, col0, height, width, ownership) in enumerate(windows):
            window = rasterio.windows.Window(col0, row0, width, height)
            image = dataset.read(1, window=window, out_dtype="float32")
            if dataset.nodata is not None:
                image[image == dataset.nodata] = np.nan
            image = apply_prepared_land_mask(
                image,
                dataset.window_transform(window),
                prepared_land,
            )
            normalized = _normalize_with_domain(
                image,
                normalization_low,
                normalization_high,
            )
            tile_candidates = adaptive_threshold_candidates(
                normalized,
                threshold_sigma=threshold_sigma,
                min_area_px=min_area_px,
                max_area_px=max_area_px,
                local_window_px=local_window_px,
                guard_window_px=guard_window_px,
                min_contrast_sigma=min_contrast_sigma,
                min_training_fraction=min_training_fraction,
            )
            for candidate in tile_candidates:
                local_row, local_col = candidate.centroid_yx
                global_row = row0 + local_row
                global_col = col0 + local_col
                if not _owned(global_row, global_col, ownership):
                    continue
                y0, x0, y1, x1 = candidate.bbox_yx
                raw_candidates.append(
                    replace(
                        candidate,
                        centroid_yx=(global_row, global_col),
                        bbox_yx=(row0 + y0, col0 + x0, row0 + y1, col0 + x1),
                    )
                )
                candidate_tiles.append(
                    {
                        "tile_index": tile_index,
                        "tile_row0": row0,
                        "tile_col0": col0,
                        "tile_height": height,
                        "tile_width": width,
                    }
                )
                if len(raw_candidates) > limits.max_candidates:
                    raise ResourceLimitError(
                        f"candidate count exceeds configured limit {limits.max_candidates}"
                    )

    profile_id = calibration_profile.get("profile_id") if calibration_profile else None
    profile_active = bool(calibration_profile and calibration_profile.get("active"))
    detections: list[VesselDetection] = []
    for candidate, tile_metadata in zip(raw_candidates, candidate_tiles, strict=True):
        ranking_score = score_candidate(
            candidate.peak_score,
            candidate.contrast_sigma,
            candidate.elongation,
            calibration_profile,
        )
        if post_filter_threshold is not None and ranking_score < post_filter_threshold:
            continue

        row, col = candidate.centroid_yx
        point = pixel_to_lonlat(row, col, context)
        scale = pixel_scale_m(row, col, context)
        major_axis_m = candidate.major_axis_px * scale.mean_m
        minor_axis_m = candidate.minor_axis_px * scale.mean_m
        area_m2 = candidate.area_px * scale.area_m2
        index = len(detections) + 1
        detections.append(
            VesselDetection(
                detection_id=f"{product_id}_{index:06d}",
                lon=point.lon,
                lat=point.lat,
                satellite=satellite,
                provider=provider,
                product_id=product_id,
                acquisition_time=acquisition_time,
                ranking_score=ranking_score,
                wake_type="vessel_candidate",
                metadata={
                    "area_px": candidate.area_px,
                    "area_m2": area_m2,
                    "equivalent_diameter_m": 2.0 * math.sqrt(area_m2 / math.pi)
                    if area_m2 > 0
                    else 0.0,
                    "centroid_yx": [row, col],
                    "bbox_yx": list(candidate.bbox_yx),
                    "major_axis_px": candidate.major_axis_px,
                    "minor_axis_px": candidate.minor_axis_px,
                    "major_axis_m": major_axis_m,
                    "minor_axis_m": minor_axis_m,
                    "orientation_image_deg": candidate.orientation_image_deg,
                    "elongation": candidate.elongation,
                    "pixel_scale_x_m": scale.x_m,
                    "pixel_scale_y_m": scale.y_m,
                    "pixel_area_m2": scale.area_m2,
                    "mean_score": candidate.score,
                    "peak_score": candidate.peak_score,
                    "background_mean": candidate.background_mean,
                    "background_std": candidate.background_std,
                    "contrast_sigma": candidate.contrast_sigma,
                    "training_count_px": candidate.training_count_px,
                    "training_fraction": candidate.training_fraction,
                    "cfar_edge_flag": candidate.edge_flag,
                    "cfar_threshold_value": candidate.threshold_value,
                    "ranking_score": ranking_score,
                    "ranking_score_kind": "calibrated_logistic"
                    if profile_active
                    else "heuristic_linear",
                    "calibration_profile_id": profile_id,
                    "phase2_post_filter_threshold": post_filter_threshold,
                    "phase2_profile_id": phase2_profile_id,
                    "detector": "local_cfar" if local_window_px > 0 else "global_threshold",
                    "threshold_sigma": threshold_sigma,
                    "min_contrast_sigma": min_contrast_sigma,
                    "min_training_fraction": min_training_fraction,
                    "local_window_px": local_window_px,
                    "guard_window_px": guard_window_px,
                    "tile_size_px": tile_size_px,
                    "tile_overlap_px": tile_overlap_px,
                    "tile_count": tile_count,
                    "raster_pixel_count": pixel_count,
                    "normalization_low_percentile": NORMALIZATION_LOW_PERCENTILE,
                    "normalization_high_percentile": NORMALIZATION_HIGH_PERCENTILE,
                    "normalization_low_value": normalization_low,
                    "normalization_high_value": normalization_high,
                    "normalization_sample_count": sample_count,
                    "land_mask_geojson": str(land_mask_geojson)
                    if land_mask_geojson
                    else None,
                    "shoreline_buffer_m": shoreline_buffer_m,
                    **tile_metadata,
                },
            )
        )
    return detections


def _normalization_domain(
    dataset: Any,
    prepared_land: Any,
    *,
    max_sample_pixels: int,
) -> tuple[float, float, int]:
    from affine import Affine
    from rasterio.enums import Resampling

    total = int(dataset.width) * int(dataset.height)
    ratio = min(1.0, math.sqrt(max(1, int(max_sample_pixels)) / max(total, 1)))
    sample_width = max(1, min(dataset.width, int(round(dataset.width * ratio))))
    sample_height = max(1, min(dataset.height, int(round(dataset.height * ratio))))
    sample = dataset.read(
        1,
        out_shape=(sample_height, sample_width),
        out_dtype="float32",
        resampling=Resampling.nearest,
    )
    if dataset.nodata is not None:
        sample[sample == dataset.nodata] = np.nan
    sample_transform = dataset.transform * Affine.scale(
        dataset.width / sample_width,
        dataset.height / sample_height,
    )
    sample = apply_prepared_land_mask(sample, sample_transform, prepared_land)
    finite = sample[np.isfinite(sample)]
    if finite.size == 0:
        raise ValueError("raster has no finite water pixels after masking")
    low, high = np.percentile(
        finite,
        [NORMALIZATION_LOW_PERCENTILE, NORMALIZATION_HIGH_PERCENTILE],
    )
    low_value = float(low)
    high_value = float(high)
    if not math.isfinite(low_value) or not math.isfinite(high_value):
        raise ValueError("normalization percentiles are non-finite")
    if high_value <= low_value:
        high_value = low_value + 1.0
    return low_value, high_value, int(finite.size)


def _normalize_with_domain(image: np.ndarray, low: float, high: float) -> np.ndarray:
    finite = np.isfinite(image)
    normalized = np.full(image.shape, np.nan, dtype="float32")
    if not finite.any():
        return normalized
    values = np.clip((image[finite] - low) / (high - low), 0.0, 1.0)
    normalized[finite] = values.astype("float32")
    return normalized


def _axis_starts(length: int, tile_size: int, overlap: int) -> list[int]:
    if length <= tile_size:
        return [0]
    step = tile_size - overlap
    starts = list(range(0, length - tile_size + 1, step))
    final = length - tile_size
    if starts[-1] != final:
        starts.append(final)
    return starts


def _ownership_bounds(
    starts: list[int],
    index: int,
    length: int,
    tile_size: int,
) -> tuple[float, float]:
    start = starts[index]
    previous_end = starts[index - 1] + tile_size if index > 0 else 0
    next_start = starts[index + 1] if index + 1 < len(starts) else length
    lower = 0.0 if index == 0 else (start + previous_end) / 2.0
    upper = (
        float(length)
        if index + 1 == len(starts)
        else (start + tile_size + next_start) / 2.0
    )
    return lower, upper


def _tile_windows(
    width: int,
    height: int,
    *,
    tile_size_px: int,
    tile_overlap_px: int,
) -> Iterator[tuple[int, int, int, int, tuple[float, float, float, float]]]:
    row_starts = _axis_starts(height, tile_size_px, tile_overlap_px)
    col_starts = _axis_starts(width, tile_size_px, tile_overlap_px)
    for row_index, row0 in enumerate(row_starts):
        tile_height = min(tile_size_px, height - row0)
        owned_row_min, owned_row_max = _ownership_bounds(
            row_starts,
            row_index,
            height,
            tile_size_px,
        )
        for col_index, col0 in enumerate(col_starts):
            tile_width = min(tile_size_px, width - col0)
            owned_col_min, owned_col_max = _ownership_bounds(
                col_starts,
                col_index,
                width,
                tile_size_px,
            )
            yield (
                row0,
                col0,
                tile_height,
                tile_width,
                (owned_row_min, owned_row_max, owned_col_min, owned_col_max),
            )


def _owned(
    row: float,
    col: float,
    bounds: tuple[float, float, float, float],
) -> bool:
    row_min, row_max, col_min, col_max = bounds
    return row_min <= row < row_max and col_min <= col < col_max


def _score_to_confidence(
    peak_score: float,
    contrast_sigma: float,
    elongation: float,
    calibration_profile: dict[str, Any] | None = None,
) -> float:
    """Compatibility wrapper; value is a ranking score, not probability."""

    return score_candidate(peak_score, contrast_sigma, elongation, calibration_profile)
