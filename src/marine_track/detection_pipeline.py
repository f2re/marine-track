from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np

from marine_track.ais import match_detection_to_ais, read_ais_csv
from marine_track.estimation import bearing_deg, speed_from_kelvin_wavelength
from marine_track.geospatial import (
    RasterGeoContext,
    lonlat_to_pixel,
    pixel_scale_m,
    pixel_to_lonlat,
)
from marine_track.models import HeadingMethod, SpeedMethod, VesselDetection
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.raster_detection import detect_candidates_from_raster
from marine_track.rendering.overview import render_overview
from marine_track.rendering.vessel_crop import render_vessel_crop
from marine_track.scene_materializer import MaterializedScene, materialize_scene_from_token
from marine_track.wake import associate_wake_axis_with_vessel, estimate_wake_wavelength_px

ProgressCallback = Callable[[str], None]


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


def report_progress(callback: ProgressCallback | None, text: str) -> None:
    if callback is not None:
        callback(text)


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def run_detection_for_token(
    token: str,
    output_dir: Path,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    max_crops: int = 10,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 31,
    guard_window_px: int = 5,
    min_contrast_sigma: float | None = None,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> DetectionRunResult:
    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)
    min_contrast_sigma = min_contrast_sigma if min_contrast_sigma is not None else env_float(
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
        0.0,
        0.0,
        100.0,
    )

    report_progress(progress_callback, "2/5 materialize · подготовка GeoTIFF/COG")
    materialized = materialize_scene_from_token(
        token,
        output_dir,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )

    report_progress(progress_callback, "3/5 detect · CFAR, scale, shape, wake/AIS")
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
        min_contrast_sigma=min_contrast_sigma,
        land_mask_geojson=land_mask_geojson,
        shoreline_buffer_m=shoreline_buffer_m,
    )
    enrich_detections_with_wakes(materialized.raster_path, detections)
    enrich_detections_with_ais(detections)

    report_progress(progress_callback, "4/5 render · обзор, crop и файлы")
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
        min_contrast_sigma=min_contrast_sigma,
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


def enrich_detections_with_ais(
    detections: list[VesselDetection],
    ais_csv: str | Path | None = None,
    match_window_min: int | None = None,
    track_window_min: int | None = None,
    max_distance_m: float | None = None,
    max_track_points: int = 200,
) -> None:
    if not detections:
        return
    raw_path = str(ais_csv or os.getenv("MARINE_TRACK_AIS_CSV", "")).strip()
    if not raw_path:
        return
    path = Path(raw_path)
    if not path.is_file():
        add_ais_warning(detections, f"AIS CSV not found: {path}")
        return

    match_window_min = match_window_min or env_int("MARINE_TRACK_AIS_MATCH_WINDOW_MIN", 30, 1, 24 * 60)
    track_window_min = track_window_min or env_int("MARINE_TRACK_AIS_TRACK_WINDOW_MIN", 60, 1, 24 * 60)
    max_distance_m = max_distance_m or env_float("MARINE_TRACK_AIS_MAX_DISTANCE_M", 3000.0, 1.0, 100_000.0)

    try:
        ais_df = read_ais_csv(path)
    except Exception as exc:
        add_ais_warning(detections, f"AIS CSV read failed: {exc}")
        return
    if ais_df.empty:
        return

    for detection in detections:
        match = match_detection_to_ais(
            detection,
            ais_df,
            time_window=timedelta(minutes=match_window_min),
            max_distance_m=max_distance_m,
        )
        if match is None:
            continue
        track = ais_track_points(
            ais_df,
            str(match["mmsi"]),
            detection.acquisition_time,
            window_min=track_window_min,
            max_points=max_track_points,
        )
        detection.validation_status = "ais_matched"
        detection.validation = {**detection.validation, "ais": match}
        detection.metadata = {
            **detection.metadata,
            "ais": {
                "source": str(path),
                "match_window_min": match_window_min,
                "track_window_min": track_window_min,
                "max_distance_m": max_distance_m,
                "match": match,
                "track": track,
            },
        }
        speed = match.get("ais_sog_knots")
        if isinstance(speed, (int, float)) and math.isfinite(float(speed)):
            detection.speed_knots = float(speed)
            detection.speed_method = SpeedMethod.AIS_SOG
            detection.speed_reference = f"ais:{match['mmsi']}"
        cog = match.get("ais_cog_deg")
        if detection.heading_deg is None and isinstance(cog, (int, float)) and math.isfinite(float(cog)):
            detection.heading_deg = float(cog) % 360.0
            detection.heading_method = HeadingMethod.AIS_COG
            detection.heading_ambiguity_deg = None


def add_ais_warning(detections: list[VesselDetection], warning: str) -> None:
    for detection in detections:
        detection.metadata = {**detection.metadata, "ais_warning": warning}


def ais_track_points(
    ais_df,
    mmsi: str,
    acquisition_time,
    window_min: int,
    max_points: int,
) -> list[dict[str, object]]:
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("pandas is required for AIS track extraction") from exc

    center = pd.Timestamp(acquisition_time)
    if center.tzinfo is None:
        center = center.tz_localize("UTC")
    start = center - pd.Timedelta(minutes=window_min)
    end = center + pd.Timedelta(minutes=window_min)
    frame = ais_df[(ais_df["mmsi"].astype(str) == str(mmsi)) & (ais_df["time"] >= start) & (ais_df["time"] <= end)]
    if frame.empty:
        return []
    if len(frame) > max_points:
        step = max(1, int(math.ceil(len(frame) / max_points)))
        frame = frame.iloc[::step]
    points: list[dict[str, object]] = []
    for _, row in frame.sort_values("time").iterrows():
        sog = row.get("sog_knots")
        cog = row.get("cog_deg")
        points.append(
            {
                "time": row["time"].isoformat(),
                "lon": float(row["lon"]),
                "lat": float(row["lat"]),
                "sog_knots": None if sog != sog else float(sog),
                "cog_deg": None if cog != cog else float(cog),
            }
        )
    return points


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

            local_yx = (row - row0, col - col0)
            association = associate_wake_axis_with_vessel(image, vessel_yx=local_yx)
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
            wake_payload = {
                "detector": "canny_hough",
                "axis_angle_image_deg": association.line.angle_deg,
                "hough_distance_px": association.line.distance_px,
                "accumulator": association.line.accumulator,
                "line_distance_to_vessel_px": association.line_distance_px,
                "score": association.score,
                "crop_size_px": crop_size_px,
                "heading_ambiguity_deg": 180.0,
            }
            wavelength = estimate_wake_wavelength_px(image, vessel_yx=local_yx, axis_angle_deg=association.line.angle_deg)
            if wavelength is not None:
                scale = pixel_scale_m(row, col, context)
                wavelength_m = wavelength.wavelength_px * scale.mean_m
                speed_mps, speed_knots = speed_from_kelvin_wavelength(wavelength_m)
                wake_payload["wavelength"] = {
                    "method": "cross_axis_profile_peaks",
                    "experimental": True,
                    "wavelength_px": wavelength.wavelength_px,
                    "wavelength_m": wavelength_m,
                    "peak_count": wavelength.peak_count,
                    "profile_length_px": wavelength.profile_length_px,
                    "prominence": wavelength.prominence,
                    "confidence": wavelength.confidence,
                    "pixel_scale_mean_m": scale.mean_m,
                    "speed_mps": speed_mps,
                    "speed_knots": speed_knots,
                    "speed_formula": "sqrt(g*wavelength_m/(2*pi))",
                }
                if detection.speed_knots is None:
                    detection.speed_knots = speed_knots
                    detection.speed_method = SpeedMethod.KELVIN_WAVELENGTH
                    detection.speed_reference = "wake_wavelength_experimental"
            detection.metadata = {**detection.metadata, "wake": wake_payload}


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
    min_contrast_sigma: float,
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
            "min_contrast_sigma": min_contrast_sigma,
            "confidence_formula": "0.50*peak_score + 0.35*contrast_sigma/8 + 0.15*shape_elongation/5",
            "land_mask_geojson": str(land_mask_geojson) if land_mask_geojson else None,
            "shoreline_buffer_m": shoreline_buffer_m,
        },
        "wake_speed_enrichment": {
            "enabled": True,
            "experimental": True,
            "method": "cross_axis_profile_peaks + deep_water_kelvin_wavelength",
            "note": "AIS SOG overrides this value when AIS match is available.",
        },
        "ais_enrichment": {
            "enabled": bool(os.getenv("MARINE_TRACK_AIS_CSV", "").strip()),
            "csv": os.getenv("MARINE_TRACK_AIS_CSV", "").strip() or None,
            "match_window_min": env_int("MARINE_TRACK_AIS_MATCH_WINDOW_MIN", 30, 1, 24 * 60),
            "track_window_min": env_int("MARINE_TRACK_AIS_TRACK_WINDOW_MIN", 60, 1, 24 * 60),
            "max_distance_m": env_float("MARINE_TRACK_AIS_MAX_DISTANCE_M", 3000.0, 1.0, 100_000.0),
        },
        "detections_count": len(detections),
        "crop_count": len(crop_pngs),
        "detections": [detection.model_dump(mode="json") for detection in detections],
        "crops": [str(path) for path in crop_pngs],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
