from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import numpy as np

from marine_track.ais import assign_detections_to_ais, read_ais_csv
from marine_track.estimation import bearing_deg, speed_from_kelvin_wavelength
from marine_track.geospatial import (
    RasterGeoContext,
    lonlat_to_pixel,
    pixel_scale_m,
    pixel_to_lonlat,
)
from marine_track.models import AISReference, HeadingMethod, KelvinSpeedProxy, VesselDetection
from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.processing_config import EffectiveDetectorConfig, load_effective_detector_config
from marine_track.provenance import (
    build_reproducibility_manifest,
    safe_path_reference,
    write_redacted_json,
)
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
    runtime_state_json: Path


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
    threshold_sigma: float | None = None,
    min_area_px: int | None = None,
    max_area_px: int | None = None,
    local_window_px: int | None = None,
    guard_window_px: int | None = None,
    min_contrast_sigma: float | None = None,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> DetectionRunResult:
    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)

    report_progress(progress_callback, "2/5 materialize · подготовка GeoTIFF/COG")
    materialized = materialize_scene_from_token(
        token,
        output_dir,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )
    runtime_state_json = write_runtime_state(run_dir / "runtime_state.json", materialized)
    effective_config = load_effective_detector_config(
        materialized.scene.sensor,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
    )
    detector_kwargs = effective_config.detector_kwargs()

    report_progress(progress_callback, "3/5 detect · CFAR, scale, shape, wake/AIS reference")
    detections = detect_candidates_from_raster(
        path=materialized.raster_path,
        satellite=materialized.scene.sensor.value,
        provider=materialized.provider,
        product_id=materialized.scene.product_id,
        acquisition_time=materialized.scene.acquisition_time,
        **detector_kwargs,
        land_mask_geojson=land_mask_geojson,
        shoreline_buffer_m=shoreline_buffer_m,
    )
    enrich_detections_with_wakes(materialized.raster_path, detections)
    enrich_detections_with_ais(detections)

    report_progress(progress_callback, "4/5 render · обзор кандидатов, crop и файлы")
    geojson = write_geojson(detections, run_dir / "candidates.geojson")
    csv = write_csv(detections, run_dir / "candidates.csv")
    parquet = write_parquet(detections, run_dir / "candidates.parquet")
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
        runtime_state_json=runtime_state_json,
        effective_config=effective_config,
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
        runtime_state_json=runtime_state_json,
    )


def write_runtime_state(path: Path, materialized: MaterializedScene) -> Path:
    """Write local-only state needed by calibration without exposing it in reports."""

    payload = {
        "schema_version": 1,
        "token": materialized.token,
        "raster_path": str(materialized.raster_path.resolve()),
        "work_dir": str(materialized.work_dir.resolve()),
        "provider": materialized.provider,
        "sensor": materialized.sensor,
        "product_id": materialized.scene.product_id,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)
    return path


def render_crops(
    raster_path: Path,
    detections: list[VesselDetection],
    crop_dir: Path,
    max_crops: int,
) -> list[Path]:
    crop_dir.mkdir(parents=True, exist_ok=True)
    ranked = sorted(detections, key=lambda item: item.ranking_score, reverse=True)[:max_crops]
    crops: list[Path] = []
    for index, detection in enumerate(ranked, start=1):
        output = crop_dir / f"candidate_{index:03d}_{detection.detection_id}.png"
        crops.append(render_vessel_crop(raster_path, detection, output, index=index))
    return crops


def enrich_detections_with_ais(
    detections: list[VesselDetection],
    ais_csv: str | Path | None = None,
    match_window_min: int | None = None,
    track_window_min: int | None = None,
    max_distance_m: float | None = None,
    max_interpolation_gap_min: int | None = None,
    ambiguity_margin_m: float | None = None,
    max_track_points: int = 200,
) -> None:
    if not detections:
        return
    raw_path = str(ais_csv or os.getenv("MARINE_TRACK_AIS_CSV", "")).strip()
    if not raw_path:
        return
    path = Path(raw_path)
    if not path.is_file():
        add_ais_warning(detections, f"AIS CSV not found: {path.name}")
        return

    match_window_min = match_window_min or env_int(
        "MARINE_TRACK_AIS_MATCH_WINDOW_MIN", 30, 1, 24 * 60
    )
    track_window_min = track_window_min or env_int(
        "MARINE_TRACK_AIS_TRACK_WINDOW_MIN", 60, 1, 24 * 60
    )
    max_distance_m = max_distance_m or env_float(
        "MARINE_TRACK_AIS_MAX_DISTANCE_M", 3000.0, 1.0, 100_000.0
    )
    max_interpolation_gap_min = max_interpolation_gap_min or env_int(
        "MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN", 20, 1, 24 * 60
    )
    ambiguity_margin_m = ambiguity_margin_m or env_float(
        "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M", 500.0, 0.0, 100_000.0
    )

    try:
        ais_df = read_ais_csv(path)
    except Exception as exc:
        add_ais_warning(detections, f"AIS CSV read failed: {type(exc).__name__}: {exc}")
        return
    if ais_df.empty:
        return

    assignments = assign_detections_to_ais(
        detections,
        ais_df,
        time_window=timedelta(minutes=match_window_min),
        max_distance_m=max_distance_m,
        max_interpolation_gap=timedelta(minutes=max_interpolation_gap_min),
        ambiguity_margin_m=ambiguity_margin_m,
    )
    for detection in detections:
        match = assignments.get(detection.detection_id)
        if match is None:
            continue
        track = ais_track_points(
            ais_df,
            str(match["mmsi"]),
            detection.acquisition_time,
            window_min=track_window_min,
            max_points=max_track_points,
        )
        cog_raw = match.get("ais_cog_deg")
        cog = float(cog_raw) % 360.0 if isinstance(cog_raw, (int, float)) else None
        sog_raw = match.get("ais_sog_knots")
        sog = float(sog_raw) if isinstance(sog_raw, (int, float)) else None
        second_raw = match.get("second_best_distance_m")
        margin_raw = match.get("distance_margin_m")
        status = str(match.get("status") or "matched")
        quality = str(match.get("reference_quality") or "usable")
        detection.references.ais = AISReference(
            status="ambiguous" if status == "ambiguous" else "matched",
            mmsi=str(match["mmsi"]),
            distance_m=float(match["distance_m"]),
            ais_lon=float(match["ais_lon"]),
            ais_lat=float(match["ais_lat"]),
            sog_knots=sog,
            cog_deg=cog,
            interpolation_gap_s=float(match.get("interpolation_gap_s") or 0.0),
            nearest_time_offset_s=float(match.get("nearest_time_offset_s") or 0.0),
            second_best_distance_m=(
                float(second_raw) if isinstance(second_raw, (int, float)) else None
            ),
            distance_margin_m=(
                float(margin_raw) if isinstance(margin_raw, (int, float)) else None
            ),
            reference_quality="ambiguous" if quality == "ambiguous" else "usable",
            track=track,
            source_reference=f"ais_csv:{path.name}",
        )
        detection.validation_status = f"ais_reference_{status}"
        detection.validation = {
            **detection.validation,
            "ais_reference": {
                "status": status,
                "reference_quality": quality,
                "not_ground_truth": True,
                "distance_m": float(match["distance_m"]),
            },
        }


def add_ais_warning(detections: list[VesselDetection], warning: str) -> None:
    for detection in detections:
        detection.metadata = {**detection.metadata, "ais_reference_warning": warning}


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
    frame = ais_df[
        (ais_df["mmsi"].astype(str) == str(mmsi))
        & (ais_df["time"] >= start)
        & (ais_df["time"] <= end)
    ]
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
            detection.wake_type = "linear_wake_axis_candidate"
            detection.heading_deg = heading
            detection.heading_method = HeadingMethod.WAKE_AXIS
            detection.heading_ambiguity_deg = 180.0
            wake_payload = {
                "detector": "canny_hough",
                "experimental": True,
                "axis_angle_image_deg": association.line.angle_deg,
                "hough_distance_px": association.line.distance_px,
                "accumulator": association.line.accumulator,
                "line_distance_to_candidate_px": association.line_distance_px,
                "score": association.score,
                "crop_size_px": crop_size_px,
                "heading_ambiguity_deg": 180.0,
            }
            wavelength = estimate_wake_wavelength_px(
                image,
                vessel_yx=local_yx,
                axis_angle_deg=association.line.angle_deg,
            )
            if wavelength is not None:
                scale = pixel_scale_m(row, col, context)
                wavelength_m = wavelength.wavelength_px * scale.mean_m
                speed_mps, speed_knots = speed_from_kelvin_wavelength(wavelength_m)
                detection.research_proxies.kelvin_speed = KelvinSpeedProxy(
                    value_knots=speed_knots,
                    value_mps=speed_mps,
                    wavelength_m=wavelength_m,
                    wavelength_px=wavelength.wavelength_px,
                    quality_score=wavelength.confidence,
                )
                wake_payload["wavelength"] = {
                    "method": "cross_axis_profile_peaks",
                    "experimental": True,
                    "wavelength_px": wavelength.wavelength_px,
                    "wavelength_m": wavelength_m,
                    "peak_count": wavelength.peak_count,
                    "profile_length_px": wavelength.profile_length_px,
                    "prominence": wavelength.prominence,
                    "quality_score": wavelength.confidence,
                    "pixel_scale_mean_m": scale.mean_m,
                    "research_speed_proxy_mps": speed_mps,
                    "research_speed_proxy_knots": speed_knots,
                    "speed_formula": "sqrt(g*wavelength_m/(2*pi))",
                }
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
    end = pixel_to_lonlat(
        row + math.sin(angle_rad) * step_px,
        col + math.cos(angle_rad) * step_px,
        context,
    )
    return bearing_deg(start, end)


def write_report_json(
    path: Path,
    token: str,
    materialized: MaterializedScene,
    detections: list[VesselDetection],
    crop_pngs: list[Path],
    runtime_state_json: Path,
    effective_config: EffectiveDetectorConfig,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float,
) -> Path:
    output_dir = path.parents[2]
    detector = effective_config.as_report_dict()
    detector.update(
        ranking_score_semantics=(
            "heuristic or explicitly promoted ranking score; not a probability"
        ),
        land_mask_reference=safe_path_reference(land_mask_geojson, output_dir),
        shoreline_buffer_m=shoreline_buffer_m,
    )
    payload = {
        "schema_version": 3,
        "result_type": "vessel_candidates",
        "result_semantics": {
            "ranking_score": "ordering/filtering score, not probability",
            "operational_speed": "null unless an independently validated estimator is used",
            "kelvin_speed": "research-only proxy",
            "ais": "external reference, not unconditional ground truth",
        },
        "token": token,
        "provider": materialized.provider,
        "sensor": materialized.sensor,
        "product_id": materialized.scene.product_id,
        "acquisition_time": materialized.scene.acquisition_time.isoformat(),
        "raster_key": materialized.raster_key,
        "raster_reference": safe_path_reference(materialized.raster_path, output_dir),
        "runtime_state_reference": safe_path_reference(runtime_state_json, output_dir),
        "raster_cache_hit": materialized.cache_hit,
        "aoi_crop": materialized.cropped,
        "detector": detector,
        "reproducibility": build_reproducibility_manifest(
            materialized,
            effective_config,
            output_dir=output_dir,
        ),
        "wake_research_proxy": {
            "enabled": True,
            "experimental": True,
            "method": "cross_axis_profile_peaks + deep_water_kelvin_wavelength",
            "note": "Never copied into operational speed.",
        },
        "ais_reference": {
            "enabled": bool(os.getenv("MARINE_TRACK_AIS_CSV", "").strip()),
            "csv_reference": safe_path_reference(
                os.getenv("MARINE_TRACK_AIS_CSV", "").strip() or None,
                output_dir,
            ),
            "assignment": "greedy_one_to_one_distance",
            "not_ground_truth": True,
            "match_window_min": env_int(
                "MARINE_TRACK_AIS_MATCH_WINDOW_MIN", 30, 1, 24 * 60
            ),
            "track_window_min": env_int(
                "MARINE_TRACK_AIS_TRACK_WINDOW_MIN", 60, 1, 24 * 60
            ),
            "max_distance_m": env_float(
                "MARINE_TRACK_AIS_MAX_DISTANCE_M", 3000.0, 1.0, 100_000.0
            ),
            "max_interpolation_gap_min": env_int(
                "MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN", 20, 1, 24 * 60
            ),
            "ambiguity_margin_m": env_float(
                "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M", 500.0, 0.0, 100_000.0
            ),
        },
        "candidates_count": len(detections),
        "crop_count": len(crop_pngs),
        "candidates": [detection.model_dump(mode="json") for detection in detections],
        "crops": [safe_path_reference(item, output_dir) for item in crop_pngs],
    }
    return write_redacted_json(path, payload, base_dir=output_dir)
