from __future__ import annotations

from datetime import datetime
from pathlib import Path

from marine_track.detection import adaptive_threshold_candidates
from marine_track.geospatial import RasterGeoContext, pixel_to_lonlat
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
) -> list[VesselDetection]:
    """Run the simple MVP candidate detector on one georeferenced raster band."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for raster detection") from exc

    with rasterio.open(path) as dataset:
        image = dataset.read(1).astype("float32")
        if dataset.nodata is not None:
            image[image == dataset.nodata] = float("nan")
        context = RasterGeoContext(transform=dataset.transform, crs=dataset.crs)

    normalized = percentile_normalize(image)
    candidates = adaptive_threshold_candidates(
        normalized,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
    )

    detections: list[VesselDetection] = []
    for idx, candidate in enumerate(candidates, start=1):
        row, col = candidate.centroid_yx
        point = pixel_to_lonlat(row, col, context)
        detections.append(
            VesselDetection(
                detection_id=f"{product_id}_{idx:06d}",
                lon=point.lon,
                lat=point.lat,
                satellite=satellite,
                provider=provider,
                product_id=product_id,
                acquisition_time=acquisition_time,
                confidence=_score_to_confidence(candidate.score),
                wake_type="ship_candidate",
            )
        )
    return detections


def _score_to_confidence(score: float) -> float:
    return max(0.0, min(1.0, float(score)))
