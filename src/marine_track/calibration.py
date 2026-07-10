from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from marine_track.geospatial import lonlat_to_pixel
from marine_track.rendering.overview import grayscale_to_bgr

CALIBRATION_SCHEMA_VERSION = 1
FEATURE_NAMES = ("peak_score", "contrast_term", "shape_term")
DEFAULT_WEIGHTS = {
    "peak_score": 0.50,
    "contrast_term": 0.35,
    "shape_term": 0.15,
}
ANSWER_NONE = "none"
ANSWER_UNCERTAIN = "uncertain"
ANSWER_SKIP = "skip"
VALID_ANSWERS = {str(index) for index in range(1, 10)} | {
    ANSWER_NONE,
    ANSWER_UNCERTAIN,
    ANSWER_SKIP,
}
_FCNTL = importlib.import_module("fcntl") if os.name == "posix" else None


@dataclass(frozen=True)
class CalibrationTargets:
    min_labels: int = 20
    min_positive: int = 5
    min_negative: int = 5


@contextmanager
def _state_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".calibration.lock").open("a+", encoding="utf-8") as lock_file:
        if _FCNTL is not None:
            _FCNTL.flock(lock_file.fileno(), _FCNTL.LOCK_EX)
        try:
            yield
        finally:
            if _FCNTL is not None:
                _FCNTL.flock(lock_file.fileno(), _FCNTL.LOCK_UN)


def calibration_root(output_dir: str | Path) -> Path:
    return Path(output_dir) / "calibration"


def profile_path(output_dir: str | Path) -> Path:
    return calibration_root(output_dir) / "profile.json"


def labels_path(output_dir: str | Path) -> Path:
    return calibration_root(output_dir) / "labels.jsonl"


def tasks_dir(output_dir: str | Path) -> Path:
    return calibration_root(output_dir) / "tasks"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_profile(targets: CalibrationTargets | None = None) -> dict[str, Any]:
    targets = targets or CalibrationTargets()
    return {
        "schema_version": CALIBRATION_SCHEMA_VERSION,
        "status": "not_started",
        "active": False,
        "updated_at": None,
        "targets": {
            "min_labels": targets.min_labels,
            "min_positive": targets.min_positive,
            "min_negative": targets.min_negative,
        },
        "labels": {
            "usable": 0,
            "positive": 0,
            "negative": 0,
            "uncertain": 0,
            "skipped": 0,
            "localization_corrections": 0,
        },
        "ranking_model": {
            "kind": "heuristic_linear",
            "feature_names": list(FEATURE_NAMES),
            "intercept": 0.0,
            "coefficients": dict(DEFAULT_WEIGHTS),
            "decision_threshold": 0.5,
            "fitted": False,
            "active": False,
        },
        "detector_recommendations": {
            "applied_automatically": False,
            "note": "CFAR generation parameters are not identifiable from candidate-only labels.",
        },
        "metrics": {"scope": "none", "note": "No calibration labels are available."},
    }


def load_calibration_profile(
    output_dir: str | Path,
    targets: CalibrationTargets | None = None,
) -> dict[str, Any]:
    path = profile_path(output_dir)
    if not path.is_file():
        return default_profile(targets)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_profile(targets)
    if not isinstance(payload, dict) or payload.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        return default_profile(targets)
    return payload


def calibration_needed(
    output_dir: str | Path,
    targets: CalibrationTargets | None = None,
) -> bool:
    return not bool(load_calibration_profile(output_dir, targets).get("active"))


def normalized_features(peak_score: float, contrast_sigma: float, elongation: float) -> dict[str, float]:
    return {
        "peak_score": _clamp(float(peak_score), 0.0, 1.0),
        "contrast_term": _clamp(float(contrast_sigma) / 8.0, 0.0, 1.0),
        "shape_term": _clamp((float(elongation) - 1.0) / 5.0, 0.0, 1.0),
    }


def score_candidate(
    peak_score: float,
    contrast_sigma: float,
    elongation: float,
    profile: dict[str, Any] | None = None,
) -> float:
    features = normalized_features(peak_score, contrast_sigma, elongation)
    model = profile.get("ranking_model") if profile and profile.get("active") else None
    if isinstance(model, dict) and model.get("kind") == "logistic":
        coefficients = model.get("coefficients") or {}
        value = float(model.get("intercept", 0.0))
        value += sum(float(coefficients.get(name, 0.0)) * features[name] for name in FEATURE_NAMES)
        return float(_sigmoid(value))
    return float(sum(DEFAULT_WEIGHTS[name] * features[name] for name in FEATURE_NAMES))


def create_next_calibration_task(
    output_dir: str | Path,
    admin_id: int,
    crop_size_px: int = 768,
) -> dict[str, Any] | None:
    output_dir = Path(output_dir)
    with _state_lock(calibration_root(output_dir)):
        answered = _answered_candidate_keys(output_dir)
        for candidate in _candidate_records(output_dir):
            if candidate["candidate_key"] in answered:
                continue
            task_id = hashlib.sha256(candidate["candidate_key"].encode()).hexdigest()[:20]
            task_path = tasks_dir(output_dir) / f"{task_id}.json"
            image_path = tasks_dir(output_dir) / f"{task_id}.png"
            if task_path.is_file() and image_path.is_file():
                task = _read_json(task_path)
                if task.get("status") == "open":
                    return task
            expected_cell = int(hashlib.sha256(task_id.encode()).hexdigest()[:8], 16) % 9 + 1
            task = {
                "schema_version": CALIBRATION_SCHEMA_VERSION,
                "task_id": task_id,
                "status": "open",
                "created_at": utc_now(),
                "claimed_by": admin_id,
                "candidate_key": candidate["candidate_key"],
                "expected_cell": expected_cell,
                "image_path": str(image_path),
                "source": candidate["source"],
                "candidate": candidate["candidate"],
                "features": candidate["features"],
            }
            _render_grid_task(candidate, image_path, expected_cell, crop_size_px)
            _atomic_write_json(task_path, task)
            return task
    return None


def submit_calibration_answer(
    output_dir: str | Path,
    task_id: str,
    admin_id: int,
    answer: str,
    targets: CalibrationTargets | None = None,
) -> dict[str, Any]:
    if answer not in VALID_ANSWERS:
        raise ValueError(f"Unsupported calibration answer: {answer}")
    output_dir = Path(output_dir)
    targets = targets or CalibrationTargets()
    with _state_lock(calibration_root(output_dir)):
        task_path = tasks_dir(output_dir) / f"{task_id}.json"
        if not task_path.is_file():
            raise FileNotFoundError(f"Calibration task not found: {task_id}")
        task = _read_json(task_path)
        if task.get("status") == "answered":
            return {
                "task": task,
                "profile": load_calibration_profile(output_dir, targets),
                "duplicate": True,
            }

        expected_cell = int(task["expected_cell"])
        selected_cell = int(answer) if answer.isdigit() else None
        label = _answer_label(answer, selected_cell, expected_cell)
        created_at = utc_now()
        record = {
            "schema_version": CALIBRATION_SCHEMA_VERSION,
            "label_id": hashlib.sha256(f"{task_id}:{admin_id}:{created_at}".encode()).hexdigest()[:24],
            "created_at": created_at,
            "admin_id": admin_id,
            "task_id": task_id,
            "candidate_key": task["candidate_key"],
            "answer": answer,
            "label": label,
            "expected_cell": expected_cell,
            "selected_cell": selected_cell,
            "localization_match": selected_cell == expected_cell if selected_cell is not None else None,
            "source": task.get("source"),
            "candidate": task.get("candidate"),
            "features": task.get("features"),
        }
        _append_jsonl(labels_path(output_dir), record)
        task.update(status="answered", answered_at=created_at, answer=answer, label=label)
        _atomic_write_json(task_path, task)
        profile = _rebuild_profile_unlocked(output_dir, targets)
        return {"task": task, "record": record, "profile": profile, "duplicate": False}


def rebuild_calibration_profile(
    output_dir: str | Path,
    targets: CalibrationTargets | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    targets = targets or CalibrationTargets()
    with _state_lock(calibration_root(output_dir)):
        return _rebuild_profile_unlocked(output_dir, targets)


def read_calibration_labels(output_dir: str | Path) -> list[dict[str, Any]]:
    path = labels_path(output_dir)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _rebuild_profile_unlocked(output_dir: Path, targets: CalibrationTargets) -> dict[str, Any]:
    records = read_calibration_labels(output_dir)
    positive = [record for record in records if record.get("label") == "positive"]
    negative = [
        record
        for record in records
        if record.get("label") in {"negative", "negative_localization"}
    ]
    usable = positive + negative
    ready = (
        len(usable) >= targets.min_labels
        and len(positive) >= targets.min_positive
        and len(negative) >= targets.min_negative
    )
    profile = default_profile(targets)
    profile.update(
        status="ready" if ready else "collecting" if records else "not_started",
        active=ready,
        updated_at=utc_now(),
    )
    profile["labels"] = {
        "usable": len(usable),
        "positive": len(positive),
        "negative": len(negative),
        "uncertain": sum(record.get("label") == "uncertain" for record in records),
        "skipped": sum(record.get("label") == "skipped" for record in records),
        "localization_corrections": sum(
            record.get("label") == "negative_localization" for record in records
        ),
    }

    if positive and negative:
        x, y = _training_arrays(positive, negative)
        intercept, coefficients = _fit_logistic(x, y)
        scores = np.asarray(
            [_sigmoid(intercept + float(row @ coefficients)) for row in x],
            dtype=float,
        )
        threshold, metrics = _select_threshold(scores, y)
        profile["ranking_model"] = {
            "kind": "logistic",
            "feature_names": list(FEATURE_NAMES),
            "intercept": float(intercept),
            "coefficients": {
                name: float(coefficients[index]) for index, name in enumerate(FEATURE_NAMES)
            },
            "decision_threshold": float(threshold),
            "fitted": True,
            "active": ready,
        }
        profile["metrics"] = {
            "scope": "in_sample_training_only",
            **metrics,
            "note": "Operational probability is not claimed; a fixed validation/test split is required.",
        }
        profile["detector_recommendations"] = _detector_recommendations(positive)
    else:
        profile["metrics"] = {
            "scope": "none",
            "note": "Both positive and negative labels are required to fit empirical coefficients.",
        }

    profile["profile_id"] = hashlib.sha256(
        json.dumps([record.get("label_id") for record in records], sort_keys=True).encode()
    ).hexdigest()[:16]
    _atomic_write_json(profile_path(output_dir), profile)
    return profile


def _answer_label(answer: str, selected_cell: int | None, expected_cell: int) -> str:
    if selected_cell == expected_cell:
        return "positive"
    if selected_cell is not None:
        return "negative_localization"
    if answer == ANSWER_NONE:
        return "negative"
    if answer == ANSWER_UNCERTAIN:
        return "uncertain"
    return "skipped"


def _training_arrays(
    positive: list[dict[str, Any]],
    negative: list[dict[str, Any]],
) -> tuple[np.ndarray, np.ndarray]:
    rows: list[list[float]] = []
    labels: list[float] = []
    for label, records in ((1.0, positive), (0.0, negative)):
        for record in records:
            raw = record.get("features") or {}
            features = normalized_features(
                float(raw.get("peak_score", 0.0)),
                float(raw.get("contrast_sigma", 0.0)),
                float(raw.get("elongation", 1.0)),
            )
            rows.append([features[name] for name in FEATURE_NAMES])
            labels.append(label)
    return np.asarray(rows, dtype=float), np.asarray(labels, dtype=float)


def _fit_logistic(x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    weights = np.asarray([DEFAULT_WEIGHTS[name] for name in FEATURE_NAMES], dtype=float)
    intercept = -0.5
    positive_count = max(1, int(np.sum(y == 1.0)))
    negative_count = max(1, int(np.sum(y == 0.0)))
    sample_weights = np.where(
        y == 1.0,
        len(y) / (2.0 * positive_count),
        len(y) / (2.0 * negative_count),
    )
    for _ in range(600):
        probabilities = 1.0 / (1.0 + np.exp(-np.clip(intercept + x @ weights, -30.0, 30.0)))
        errors = (probabilities - y) * sample_weights
        weights -= 0.20 * (x.T @ errors / len(y) + 0.03 * weights)
        intercept -= 0.20 * float(np.mean(errors))
    return intercept, weights


def _select_threshold(scores: np.ndarray, y: np.ndarray) -> tuple[float, dict[str, float]]:
    candidates = sorted({0.25, 0.5, 0.75, *(float(value) for value in scores)})
    best_objective = -1.0
    best_threshold = 0.5
    best_metrics: dict[str, float] = {}
    for threshold in candidates:
        predicted = scores >= threshold
        true_positive = int(np.sum(predicted & (y == 1.0)))
        false_positive = int(np.sum(predicted & (y == 0.0)))
        false_negative = int(np.sum((~predicted) & (y == 1.0)))
        true_negative = int(np.sum((~predicted) & (y == 0.0)))
        precision = true_positive / max(1, true_positive + false_positive)
        recall = true_positive / max(1, true_positive + false_negative)
        f1 = 2.0 * precision * recall / max(1e-12, precision + recall)
        specificity = true_negative / max(1, true_negative + false_positive)
        balanced_accuracy = 0.5 * (recall + specificity)
        objective = 0.65 * f1 + 0.35 * balanced_accuracy
        if objective > best_objective or (
            math.isclose(objective, best_objective) and threshold > best_threshold
        ):
            best_objective = objective
            best_threshold = threshold
            best_metrics = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "specificity": specificity,
                "balanced_accuracy": balanced_accuracy,
                "accuracy": (true_positive + true_negative) / max(1, len(y)),
            }
    return best_threshold, best_metrics


def _detector_recommendations(positive: list[dict[str, Any]]) -> dict[str, Any]:
    contrast = np.asarray(
        [float((record.get("features") or {}).get("contrast_sigma", 0.0)) for record in positive]
    )
    area = np.asarray(
        [float((record.get("features") or {}).get("area_px", 0.0)) for record in positive]
    )
    return {
        "applied_automatically": False,
        "min_contrast_sigma": float(max(0.0, np.percentile(contrast, 10) * 0.75)),
        "min_area_px": int(max(1, math.floor(np.percentile(area, 5)))) if np.any(area > 0) else 1,
        "max_area_px": int(max(2, math.ceil(np.percentile(area, 95) * 1.5)))
        if np.any(area > 0)
        else 5000,
        "threshold_sigma": None,
        "local_window_px": None,
        "guard_window_px": None,
        "note": (
            "Candidate-only labels tune ranking and post-filter recommendations, but cannot "
            "identify missed targets below the current CFAR threshold."
        ),
    }


def _candidate_records(output_dir: Path) -> Iterator[dict[str, Any]]:
    reports = list((output_dir / "detections").glob("*/report.json"))
    reports.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for report_path in reports:
        try:
            report = _read_json(report_path)
        except (OSError, ValueError):
            continue
        raster_path = Path(str(report.get("raster_path") or ""))
        detections = report.get("detections") or []
        if not raster_path.is_file() or not isinstance(detections, list):
            continue
        for detection in detections:
            if not isinstance(detection, dict):
                continue
            metadata = detection.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            detection_id = str(detection.get("detection_id") or "")
            wake = metadata.get("wake")
            yield {
                "candidate_key": f"{report.get('product_id')}:{detection_id}",
                "source": {
                    "report_path": str(report_path),
                    "raster_path": str(raster_path),
                    "token": report.get("token"),
                    "sensor": report.get("sensor"),
                    "provider": report.get("provider"),
                    "product_id": report.get("product_id"),
                    "acquisition_time": report.get("acquisition_time"),
                },
                "candidate": {
                    "detection_id": detection_id,
                    "lon": detection.get("lon"),
                    "lat": detection.get("lat"),
                    "ranking_score": detection.get("confidence"),
                },
                "features": {
                    "peak_score": metadata.get("peak_score", 0.0),
                    "contrast_sigma": metadata.get("contrast_sigma", 0.0),
                    "elongation": metadata.get("elongation", 1.0),
                    "area_px": metadata.get("area_px", 0.0),
                    "major_axis_px": metadata.get("major_axis_px", 0.0),
                    "minor_axis_px": metadata.get("minor_axis_px", 0.0),
                    "wake_score": wake.get("score") if isinstance(wake, dict) else None,
                    "ais_matched": detection.get("validation_status") == "ais_matched",
                },
            }


def _render_grid_task(
    candidate: dict[str, Any],
    output_path: Path,
    expected_cell: int,
    crop_size_px: int,
) -> None:
    try:
        import rasterio
        from rasterio.windows import Window
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rasterio is required for calibration task rendering") from exc

    crop_size_px = max(384, min(1200, int(crop_size_px)))
    crop_size_px -= crop_size_px % 3
    source = candidate["source"]
    detection = candidate["candidate"]
    with rasterio.open(Path(source["raster_path"])) as dataset:
        row, col = lonlat_to_pixel(
            float(detection["lon"]),
            float(detection["lat"]),
            dataset.transform,
            dataset.crs,
        )
        cell_size = crop_size_px // 3
        cell_row, cell_col = divmod(expected_cell - 1, 3)
        desired_y = cell_row * cell_size + cell_size // 2
        desired_x = cell_col * cell_size + cell_size // 2
        row0 = int(round(row - desired_y))
        col0 = int(round(col - desired_x))
        fill_value = dataset.nodata if dataset.nodata is not None else np.nan
        image = dataset.read(
            1,
            window=Window(col0, row0, crop_size_px, crop_size_px),
            boundless=True,
            out_dtype="float32",
            fill_value=fill_value,
        )
        if dataset.nodata is not None:
            image[image == dataset.nodata] = np.nan

    canvas = grayscale_to_bgr(image)
    _draw_grid(canvas)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), canvas):
        raise RuntimeError(f"Failed to write calibration image: {output_path}")


def _draw_grid(canvas: np.ndarray) -> None:
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
            cv2.LINE_AA,
        )


def _answered_candidate_keys(output_dir: Path) -> set[str]:
    return {
        str(record["candidate_key"])
        for record in read_calibration_labels(output_dir)
        if record.get("candidate_key")
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        file_obj.flush()
        os.fsync(file_obj.fileno())


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-min(value, 60.0)))
    exponent = math.exp(max(value, -60.0))
    return exponent / (1.0 + exponent)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
