from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from marine_track.calibration_phase2 import (
    FEATURE_SET_VERSION,
    PHASE2_SCHEMA_VERSION,
    STRATA,
    TASK_GENERATOR_VERSION,
    Phase2Targets,
    applicability_key,
    assign_split,
    atomic_write_json,
    manifest_path,
    phase2_root,
    read_json,
    read_phase2_labels,
    scene_group_id,
    tasks_dir,
    utc_now,
)
from marine_track.geospatial import lonlat_to_pixel, pixel_to_lonlat
from marine_track.rendering.overview import grayscale_to_bgr


def applicability_from_report(report: dict[str, Any], dataset: Any | None = None) -> dict[str, Any]:
    detector = report.get("detector") if isinstance(report.get("detector"), dict) else {}
    source = report.get("source") if isinstance(report.get("source"), dict) else {}
    gsd = None
    if dataset is not None:
        try:
            gsd = float((abs(dataset.transform.a) + abs(dataset.transform.e)) / 2.0)
        except (AttributeError, TypeError, ValueError):
            gsd = None
    gsd_bucket = "unknown"
    if gsd is not None and math.isfinite(gsd):
        if gsd <= 5:
            gsd_bucket = "lte5m"
        elif gsd <= 15:
            gsd_bucket = "5-15m"
        elif gsd <= 40:
            gsd_bucket = "15-40m"
        else:
            gsd_bucket = "gt40m"
    processing = {
        "sensor": str(report.get("sensor") or "unknown").lower(),
        "collection": str(report.get("collection") or source.get("collection") or "unknown").lower(),
        "processing_level": str(
            report.get("processing_level") or source.get("processing_level") or "unknown"
        ).lower(),
        "polarization": str(report.get("polarization") or source.get("polarization") or "unknown").lower(),
        "band": str(report.get("band") or source.get("band") or "unknown").lower(),
        "units": str(report.get("units") or source.get("units") or "unknown").lower(),
        "gsd_bucket": gsd_bucket,
        "detector": str(detector.get("name") or "unknown").lower(),
    }
    processing["processing_config_hash"] = hashlib.sha256(
        json.dumps(detector, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]
    return processing


def generate_independent_tasks(
    output_dir: str | Path,
    targets: Phase2Targets | None = None,
    context_geojson: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    targets = targets or Phase2Targets()
    output_dir = Path(output_dir)
    phase2_root(output_dir).mkdir(parents=True, exist_ok=True)
    existing = _read_manifest(output_dir)
    known_ids = {str(item.get("task_id")) for item in existing.get("tasks", [])}
    if force:
        known_ids.clear()
    created: list[dict[str, Any]] = []
    for report_path in _report_paths(output_dir):
        created.extend(
            _tasks_from_report(
                report_path,
                targets=targets,
                context_geojson=Path(context_geojson) if context_geojson else None,
                known_ids=known_ids,
            )
        )
    tasks = [item for item in existing.get("tasks", []) if not force] + created
    tasks.sort(key=lambda item: (str(item.get("split")), str(item.get("task_id"))))
    payload = {
        "schema_version": PHASE2_SCHEMA_VERSION,
        "task_generator_version": TASK_GENERATOR_VERSION,
        "feature_set_version": FEATURE_SET_VERSION,
        "updated_at": utc_now(),
        "tasks": tasks,
        "counts": _count_by(tasks, "stratum"),
        "splits": _count_by(tasks, "split"),
    }
    atomic_write_json(manifest_path(output_dir), payload)
    return payload


def create_next_independent_task(
    output_dir: str | Path,
    admin_id: int,
    targets: Phase2Targets | None = None,
    context_geojson: str | Path | None = None,
) -> dict[str, Any] | None:
    targets = targets or Phase2Targets()
    manifest = generate_independent_tasks(output_dir, targets, context_geojson)
    answered = {str(item.get("task_id")) for item in read_phase2_labels(output_dir)}
    open_tasks = [
        item
        for item in manifest.get("tasks", [])
        if item.get("task_id") not in answered and item.get("status", "open") == "open"
    ]
    if not open_tasks:
        return None
    priority = {name: index for index, name in enumerate(STRATA)}
    counts: dict[str, int] = defaultdict(int)
    for record in read_phase2_labels(output_dir):
        counts[str(record.get("stratum"))] += 1
    open_tasks.sort(
        key=lambda item: (
            counts[str(item.get("stratum"))],
            priority.get(str(item.get("stratum")), len(priority)),
            str(item.get("task_id")),
        )
    )
    task = dict(open_tasks[0])
    task["claimed_by"] = admin_id
    task["claimed_at"] = utc_now()
    atomic_write_json(tasks_dir(output_dir) / f"{task['task_id']}.json", task)
    return task


def _runtime_raster_path(report_path: Path, report: dict[str, Any]) -> Path:
    runtime_reference = report.get("runtime_state_reference")
    if isinstance(runtime_reference, str) and runtime_reference:
        state_path = Path(runtime_reference)
        if not state_path.is_absolute():
            state_path = report_path.parents[2] / state_path
        try:
            state = read_json(state_path)
            raster_path = Path(str(state.get("raster_path") or ""))
            if raster_path.is_file():
                return raster_path
        except (OSError, ValueError):
            pass
    return Path(str(report.get("raster_path") or ""))


def _tasks_from_report(
    report_path: Path,
    targets: Phase2Targets,
    context_geojson: Path | None,
    known_ids: set[str],
) -> list[dict[str, Any]]:
    try:
        import rasterio
        from rasterio.windows import Window
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("rasterio is required for phase 2 calibration") from exc
    report = read_json(report_path)
    raster_path = _runtime_raster_path(report_path, report)
    if not raster_path.is_file():
        return []
    contexts = _load_context(context_geojson)
    tasks: list[dict[str, Any]] = []
    with rasterio.open(raster_path) as dataset:
        tile_size = max(384, min(1536, int(targets.tile_size_px)))
        tile_size -= tile_size % 3
        applicability = applicability_from_report(report, dataset)
        group_id = scene_group_id({**report, "raster_key": report.get("raster_key")})
        split = assign_split(group_id)
        scored: list[tuple[float, dict[str, Any]]] = []
        for row0, col0 in _deterministic_windows(dataset.width, dataset.height, tile_size):
            image = dataset.read(
                1,
                window=Window(col0, row0, tile_size, tile_size),
                boundless=True,
                out_dtype="float32",
                fill_value=dataset.nodata if dataset.nodata is not None else np.nan,
            )
            if dataset.nodata is not None:
                image[image == dataset.nodata] = np.nan
            valid_fraction = float(np.mean(np.isfinite(image)))
            if valid_fraction < min(0.5, targets.min_valid_fraction):
                continue
            stats = _tile_stats(image)
            center = pixel_to_lonlat(
                row0 + tile_size / 2,
                col0 + tile_size / 2,
                _geo_context(dataset),
            )
            explicit = _context_stratum(center.lon, center.lat, contexts)
            stratum = explicit or _infer_stratum(valid_fraction, stats)
            if stratum == "open_sea" and valid_fraction < targets.min_valid_fraction:
                continue
            task_id = hashlib.sha256(
                f"{group_id}:{row0}:{col0}:{tile_size}:{TASK_GENERATOR_VERSION}".encode()
            ).hexdigest()[:20]
            if task_id in known_ids:
                continue
            prediction = _prediction_for_window(report, dataset, row0, col0, tile_size)
            source = {
                "report_path": str(report_path),
                "raster_path": str(raster_path),
                "product_id": report.get("product_id"),
                "token": report.get("token"),
                "sensor": report.get("sensor"),
                "provider": report.get("provider"),
                "acquisition_time": report.get("acquisition_time"),
                "relative_orbit": report.get("relative_orbit"),
                "raster_key": report.get("raster_key"),
            }
            task = {
                "schema_version": PHASE2_SCHEMA_VERSION,
                "task_generator_version": TASK_GENERATOR_VERSION,
                "feature_set_version": FEATURE_SET_VERSION,
                "task_id": task_id,
                "status": "open",
                "created_at": utc_now(),
                "group_id": group_id,
                "split": split,
                "stratum": stratum,
                "scene_regime": stratum,
                "applicability": applicability,
                "applicability_key": applicability_key(applicability, stratum),
                "window": {"row0": row0, "col0": col0, "size_px": tile_size},
                "valid_fraction": valid_fraction,
                "water_mask_source": "explicit_context" if explicit else "valid_data_proxy",
                "tile_stats": stats,
                "tile_area_km2": _tile_area_km2(dataset, tile_size),
                "prediction": prediction,
                "reference": _reference_quality(prediction),
                "source": source,
                "image_path": str(tasks_dir(report_path.parents[2]) / f"{task_id}.png"),
            }
            scored.append((_stratum_priority_score(stratum, stats, valid_fraction), task))
        scored.sort(key=lambda item: (-item[0], item[1]["task_id"]))
        per_stratum: dict[str, int] = defaultdict(int)
        for _, task in scored:
            if len(tasks) >= targets.max_tiles_per_scene:
                break
            stratum = str(task["stratum"])
            limit = max(2, math.ceil(targets.max_tiles_per_scene / len(STRATA)))
            if per_stratum[stratum] >= limit and any(per_stratum[name] < limit for name in STRATA):
                continue
            _render_task_image(task, dataset)
            atomic_write_json(tasks_dir(report_path.parents[2]) / f"{task['task_id']}.json", task)
            tasks.append(task)
            known_ids.add(task["task_id"])
            per_stratum[stratum] += 1
    return tasks


def _deterministic_windows(width: int, height: int, size: int) -> Iterator[tuple[int, int]]:
    step = max(size // 2, 1)
    rows = list(range(0, max(1, height - size + 1), step)) or [0]
    cols = list(range(0, max(1, width - size + 1), step)) or [0]
    if rows[-1] != max(0, height - size):
        rows.append(max(0, height - size))
    if cols[-1] != max(0, width - size):
        cols.append(max(0, width - size))
    pairs = [(row, col) for row in rows for col in cols]
    pairs.sort(key=lambda pair: hashlib.sha256(f"{pair[0]}:{pair[1]}".encode()).hexdigest())
    yield from pairs


def _render_task_image(task: dict[str, Any], dataset: Any) -> None:
    from rasterio.windows import Window

    window = task["window"]
    image = dataset.read(
        1,
        window=Window(window["col0"], window["row0"], window["size_px"], window["size_px"]),
        boundless=True,
        out_dtype="float32",
        fill_value=dataset.nodata if dataset.nodata is not None else np.nan,
    )
    if dataset.nodata is not None:
        image[image == dataset.nodata] = np.nan
    canvas = grayscale_to_bgr(image)
    height, width = canvas.shape[:2]
    for index in (1, 2):
        x = round(width * index / 3)
        y = round(height * index / 3)
        cv2.line(canvas, (x, 0), (x, height - 1), (0, 0, 0), 5, cv2.LINE_AA)
        cv2.line(canvas, (x, 0), (x, height - 1), (255, 255, 255), 2, cv2.LINE_AA)
        cv2.line(canvas, (0, y), (width - 1, y), (0, 0, 0), 5, cv2.LINE_AA)
        cv2.line(canvas, (0, y), (width - 1, y), (255, 255, 255), 2, cv2.LINE_AA)
    for cell in range(1, 10):
        row, col = divmod(cell - 1, 3)
        x = round(col * width / 3) + 12
        y = round(row * height / 3) + 34
        cv2.rectangle(canvas, (x - 7, y - 27), (x + 38, y + 9), (0, 0, 0), -1)
        cv2.putText(
            canvas,
            str(cell),
            (x, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (255, 255, 255),
            2,
        )
    path = Path(str(task["image_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), canvas):
        raise RuntimeError(f"Failed to write phase 2 task image: {path}")


def _prediction_for_window(
    report: dict[str, Any],
    dataset: Any,
    row0: int,
    col0: int,
    size: int,
) -> dict[str, Any]:
    inside: list[dict[str, Any]] = []
    for detection in report.get("candidates") or report.get("detections") or []:
        if not isinstance(detection, dict):
            continue
        try:
            row, col = lonlat_to_pixel(
                float(detection["lon"]),
                float(detection["lat"]),
                dataset.transform,
                dataset.crs,
            )
        except (KeyError, TypeError, ValueError):
            continue
        if row0 <= row < row0 + size and col0 <= col < col0 + size:
            metadata = detection.get("metadata") if isinstance(detection.get("metadata"), dict) else {}
            references = detection.get("references") if isinstance(detection.get("references"), dict) else {}
            inside.append(
                {
                    "detection_id": detection.get("detection_id"),
                    "row": float(row),
                    "col": float(col),
                    "lon": detection.get("lon"),
                    "lat": detection.get("lat"),
                    "ranking_score": detection.get("ranking_score", detection.get("confidence")),
                    "validation_status": detection.get("validation_status"),
                    "ais": references.get("ais") or metadata.get("ais"),
                }
            )
    scores = [
        float(item["ranking_score"])
        for item in inside
        if isinstance(item.get("ranking_score"), (int, float))
    ]
    return {
        "candidate_count": len(inside),
        "max_ranking_score": max(scores) if scores else None,
        "candidates": inside,
    }


def _reference_quality(prediction: dict[str, Any]) -> dict[str, Any]:
    matched = [
        item
        for item in prediction.get("candidates", [])
        if str(item.get("validation_status") or "").startswith("ais_reference_")
    ]
    if not matched:
        return {"ais_status": "unavailable", "ground_truth": False}
    return {
        "ais_status": "candidate_reference",
        "ground_truth": False,
        "matched_candidates": len(matched),
        "note": "AIS assists review but is not unconditional ground truth.",
    }


def _tile_stats(image: np.ndarray) -> dict[str, float]:
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return {"mean": 0.0, "std": 0.0, "p95": 0.0, "gradient": 0.0}
    mean = float(np.mean(finite))
    std = float(np.std(finite))
    p95 = float(np.percentile(finite, 95))
    filled = np.where(np.isfinite(image), image, mean).astype("float64")
    gy, gx = np.gradient(filled)
    return {
        "mean": mean,
        "std": std,
        "p95": p95,
        "gradient": float(np.mean(np.hypot(gx, gy))),
    }


def _infer_stratum(valid_fraction: float, stats: dict[str, float]) -> str:
    if valid_fraction < 0.95:
        return "coastline"
    if stats["std"] > max(0.08, abs(stats["mean"]) * 0.35) or stats["gradient"] > 0.06:
        return "high_clutter"
    return "open_sea"


def _stratum_priority_score(stratum: str, stats: dict[str, float], valid_fraction: float) -> float:
    base = {
        "port": 5.0,
        "offshore_structure": 4.0,
        "coastline": 3.0,
        "high_clutter": 2.0,
        "open_sea": 1.0,
    }.get(stratum, 0.0)
    return base + stats["std"] + stats["gradient"] + valid_fraction * 0.01


def _load_context(path: Path | None) -> list[tuple[str, Any]]:
    if path is None or not path.is_file():
        return []
    try:
        from shapely.geometry import shape
    except ImportError:
        return []
    payload = read_json(path)
    contexts: list[tuple[str, Any]] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, dict):
            continue
        properties = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        stratum = str(properties.get("stratum") or "")
        if stratum not in STRATA:
            continue
        try:
            contexts.append((stratum, shape(feature.get("geometry"))))
        except Exception:
            continue
    return contexts


def _context_stratum(lon: float, lat: float, contexts: list[tuple[str, Any]]) -> str | None:
    if not contexts:
        return None
    try:
        from shapely.geometry import Point
    except ImportError:
        return None
    point = Point(lon, lat)
    for stratum, geometry in contexts:
        if geometry.contains(point) or geometry.touches(point):
            return stratum
    return None


def _tile_area_km2(dataset: Any, size: int) -> float:
    try:
        pixel_area = abs(float(dataset.transform.a) * float(dataset.transform.e))
    except (AttributeError, TypeError, ValueError):
        pixel_area = 0.0
    if dataset.crs and getattr(dataset.crs, "is_geographic", False):
        try:
            from pyproj import Geod

            context = _geo_context(dataset)
            first = pixel_to_lonlat(0.0, 0.0, context)
            second = pixel_to_lonlat(float(size), float(size), context)
            geod = Geod(ellps="WGS84")
            width_m = abs(geod.inv(first.lon, first.lat, second.lon, first.lat)[2])
            height_m = abs(geod.inv(first.lon, first.lat, first.lon, second.lat)[2])
            return width_m * height_m / 1_000_000.0
        except Exception:
            return 0.0
    return pixel_area * size * size / 1_000_000.0


def _geo_context(dataset: Any) -> Any:
    from marine_track.geospatial import RasterGeoContext

    return RasterGeoContext(transform=dataset.transform, crs=dataset.crs)


def _report_paths(output_dir: Path) -> list[Path]:
    paths = list((output_dir / "detections").glob("*/report.json"))
    paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return paths


def _read_manifest(output_dir: Path) -> dict[str, Any]:
    path = manifest_path(output_dir)
    if not path.is_file():
        return {"tasks": []}
    try:
        return read_json(path)
    except (OSError, ValueError):
        return {"tasks": []}


def _count_by(items: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[str(item.get(key) or "unknown")] += 1
    return dict(sorted(counts.items()))
