from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from marine_track.models import VesselDetection
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.raster_detection import detect_candidates_from_raster
from marine_track.rendering.overview import render_overview
from marine_track.rendering.vessel_crop import render_vessel_crop
from marine_track.scene_materializer import MaterializedScene, materialize_scene_from_token


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
) -> DetectionRunResult:
    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)
    materialized = materialize_scene_from_token(token, output_dir, cache_dir=run_dir / "assets")
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
    )

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
) -> Path:
    payload = {
        "token": token,
        "provider": materialized.provider,
        "sensor": materialized.sensor,
        "product_id": materialized.scene.product_id,
        "acquisition_time": materialized.scene.acquisition_time.isoformat(),
        "raster_key": materialized.raster_key,
        "raster_path": str(materialized.raster_path),
        "aoi_crop": materialized.cropped,
        "detector": {
            "name": "local_cfar" if local_window_px > 0 else "global_threshold",
            "threshold_sigma": threshold_sigma,
            "min_area_px": min_area_px,
            "max_area_px": max_area_px,
            "local_window_px": local_window_px,
            "guard_window_px": guard_window_px,
        },
        "detections_count": len(detections),
        "crop_count": len(crop_pngs),
        "detections": [detection.model_dump(mode="json") for detection in detections],
        "crops": [str(path) for path in crop_pngs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
