from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from marine_track.detection import adaptive_threshold_candidates
from marine_track.geospatial import RasterGeoContext, pixel_scale_m, pixel_to_lonlat
from marine_track.land_mask import apply_land_mask
from marine_track.models import VesselDetection
from marine_track.raster import percentile_normalize


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
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
) -> list[VesselDetection]:
    """Run the MVP candidate detector on one georeferenced raster band."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for raster detection") from exc

    with rasterio.open(path) as dataset:
        image = dataset.read(1).astype("float32")
        if dataset.nodata is not None:
            image[image == dataset.nodata] = float("nan")
        image = apply_land_mask(
            image,
            dataset.transform,
            dataset.crs,
            land_mask_geojson,
            shoreline_buffer_m,
        )
        context = RasterGeoContext(transform=dataset.transform, crs=dataset.crs)

    normalized = percentile_normalize(image)
    candidates = adaptive_threshold_candidates(
        normalized,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
    )

    detections: list[VesselDetection] = []
    for idx, candidate in enumerate(candidates, start=1):
        row, col = candidate.centroid_yx
        point = pixel_to_lonlat(row, col, context)
        scale = pixel_scale_m(row, col, context)
        major_axis_m = candidate.major_axis_px * scale.mean_m
        minor_axis_m = candidate.minor_axis_px * scale.mean_m
        area_m2 = candidate.area_px * scale.area_m2
        detections.append(
            VesselDetection(
                detection_id=f"{product_id}_{idx:06d}",
                lon=point.lon,
                lat=point.lat,
                satellite=satellite,
                provider=provider,
                product_id=product_id,
                acquisition_time=acquisition_time,
                confidence=_score_to_confidence(candidate.peak_score, candidate.contrast_sigma, candidate.elongation),
                wake_type="ship_candidate",
                metadata={
                    "area_px": candidate.area_px,
                    "area_m2": area_m2,
                    "equivalent_diameter_m": 2.0 * math.sqrt(area_m2 / math.pi) if area_m2 > 0 else 0.0,
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
                    "detector": "local_cfar" if local_window_px > 0 else "global_threshold",
                    "threshold_sigma": threshold_sigma,
                    "min_contrast_sigma": min_contrast_sigma,
                    "local_window_px": local_window_px,
                    "guard_window_px": guard_window_px,
                    "land_mask_geojson": str(land_mask_geojson) if land_mask_geojson else None,
                    "shoreline_buffer_m": shoreline_buffer_m,
                },
            )
        )
    return detections


def _score_to_confidence(peak_score: float, contrast_sigma: float, elongation: float) -> float:
    contrast_term = max(0.0, min(1.0, contrast_sigma / 8.0))
    peak_term = max(0.0, min(1.0, float(peak_score)))
    shape_term = max(0.0, min(1.0, (elongation - 1.0) / 5.0))
    return max(0.0, min(1.0, 0.50 * peak_term + 0.35 * contrast_term + 0.15 * shape_term))
