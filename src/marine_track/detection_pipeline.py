from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from marine_track.estimation import bearing_deg
from marine_track.geospatial import RasterGeoContext, lonlat_to_pixel, pixel_to_lonlat
from marine_track.models import HeadingMethod, VesselDetection
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.raster_detection import detect_candidates_from_raster
from marine_track.rendering.overview import render_overview
from marine_track.rendering.vessel_crop import render_vessel_crop
from marine_track.scene_materializer import MaterializedScene, materialize_scene_from_token
from marine_track.wake import associate_wake_axis_with_vessel


@dataclass(frozen=True)
class DetectionRunResult:
    token: str
    materialized: MaterializedScene
    detections: list[VesselDetection]
    overview_png: Path
    crop_pngs: list[Path]
    geojson: Path
    csv: Path
    parquet: Path
    report_json: Path


def run_detection_for_token(
    token: str,
    output_dir: Path,
    max_crops: int = 10,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 31,
    guard_window_px: int = 5,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
) -> DetectionRunResult:
    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)
    materialized = materialize_scene_from_token(token, output_dir)
    detections = detect_candidates_from_raster(
        path=materialized.raster_path,
        satellite=materialized.scene.sensor.value,
        provider=materialized.provider,
        product_id=materialized.scene.product_id,
        acquisition_time=materialized.scene.acquisition_time,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        land_mask_geojson=land_mask_geojson,
        shoreline_buffer_m=shoreline_buffer_m,
    )
    enrich_detections_with_wakes(materialized.raster_path, detections)

    geojson = write_geojson(detections, run_dir / "detections.geojson")
    csv = write_csv(detections, run_dir / "detections.csv")
    parquet = write_parquet(detections, run_dir / "detections.parquet")
    overview_png = render_overview(
        materialized.raster_path,
        detections,
        run_dir / "overview.png",
        title=f"{materialized.scene.sensor.value} {materialized.scene.acquisition_time.isoformat()}",
    )
    crop_pngs = render_crops(materialized.raster_path, detections, run_dir / "crops", max_crops)
    report_json = write_report_json(
        run_dir / "report.json",
        token,
        materialized,
        detections,
        crop_pngs,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        land_mask_geojson=land_mask_geojson,
        shoreline_buffer_m=shoreline_buffer_m,
    )
    return DetectionRunResult(
        token=token,
        materialized=materialized,
        detections=detections,
        overview_png=overview_png,
        crop_pngs=crop_pngs,
        geojson=geojson,
        csv=csv,
        parquet=parquet,
        report_json=report_json,
    )


def render_crops(
    raster_path: Path,
    detections: list[VesselDetection],
    crop_dir: Path,
    max_crops: int,
) -> list[Path]:
    crop_dir.mkdir(parents=True, exist_ok=True)
    ranked = sorted(detections, key=lambda item: item.confidence, reverse=True)[:max_crops]
    crops: list[Path] = []
    for index, detection in enumerate(ranked, start=1):
        output = crop_dir / f"vessel_{index:03d}_{detection.detection_id}.png"
        crops.append(render_vessel_crop(raster_path, detection, output, index=index))
    return crops


def enrich_detections_with_wakes(
    raster_path: Path,
    detections: list[VesselDetection],
    crop_size_px: int = 512,
) -> None:
    if not detections:
        return
    try:
        import rasterio
        from rasterio.windows import Window
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for wake enrichment") from exc

    with rasterio.open(raster_path) as dataset:
        context = RasterGeoContext(transform=dataset.transform, crs=dataset.crs)
        for detection in detections:
            row, col = lonlat_to_pixel(detection.lon, detection.lat, dataset.transform, dataset.crs)
            row_i = int(round(row))
            col_i = int(round(col))
            half = crop_size_px // 2
            row0 = max(0, row_i - half)
            col0 = max(0, col_i - half)
            row1 = min(dataset.height, row0 + crop_size_px)
            col1 = min(dataset.width, col0 + crop_size_px)
            row0 = max(0, row1 - crop_size_px)
            col0 = max(0, col1 - crop_size_px)
            window = Window(col0, row0, col1 - col0, row1 - row0)
            image = dataset.read(1, window=window).astype("float32")
            if dataset.nodata is not None:
                image[image == dataset.nodata] = np.nan

            association = associate_wake_axis_with_vessel(image, vessel_yx=(row - row0, col - col0))
            if association is None:
                continue

            heading = image_axis_to_geographic_heading(
                association.line.angle_deg,
                row=row,
                col=col,
                context=context,
            )
            detection.wake_type = "linear_wake_axis"
            detection.heading_deg = heading
            detection.heading_method = HeadingMethod.WAKE_AXIS
            detection.heading_ambiguity_deg = 180.0
            detection.metadata = {
                **detection.metadata,
                "wake": {
                    "detector": "canny_hough",
                    "axis_angle_image_deg": association.line.angle_deg,
                    "hough_distance_px": association.line.distance_px,
                    "accumulator": association.line.accumulator,
                    "line_distance_to_vessel_px": association.line_distance_px,
                    "score": association.score,
                    "crop_size_px": crop_size_px,
                    "heading_ambiguity_deg": 180.0,
                },
            }


def image_axis_to_geographic_heading(
    angle_deg: float,
    row: float,
    col: float,
    context: RasterGeoContext,
    step_px: float = 32.0,
) -> float:
    angle_rad = math.radians(angle_deg)
    start = pixel_to_lonlat(row, col, context)
    end = pixel_to_lonlat(row + math.sin(angle_rad) * step_px, col + math.cos(angle_rad) * step_px, context)
    return bearing_deg(start, end)


def write_report_json(
    path: Path,
    token: str,
    materialized: MaterializedScene,
    detections: list[VesselDetection],
    crop_pngs: list[Path],
    threshold_sigma: float,
    min_area_px: int,
    max_area_px: int,
    local_window_px: int,
    guard_window_px: int,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float,
) -> Path:
    payload = {
        "token": token,
        "provider": materialized.provider,
        "sensor": materialized.sensor,
        "product_id": materialized.scene.product_id,
        "acquisition_time": materialized.scene.acquisition_time.isoformat(),
        "raster_key": materialized.raster_key,
        "raster_path": str(materialized.raster_path),
        "raster_cache_hit": materialized.cache_hit,
        "aoi_crop": materialized.cropped,
        "detector": {
            "name": "local_cfar" if local_window_px > 0 else "global_threshold",
            "threshold_sigma": threshold_sigma,
            "min_area_px": min_area_px,
            "max_area_px": max_area_px,
            "local_window_px": local_window_px,
            "guard_window_px": guard_window_px,
            "land_mask_geojson": str(land_mask_geojson) if land_mask_geojson else None,
            "shoreline_buffer_m": shoreline_buffer_m,
        },
        "detections_count": len(detections),
        "crop_count": len(crop_pngs),
        "detections": [detection.model_dump(mode="json") for detection in detections],
        "crops": [str(path) for path in crop_pngs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
