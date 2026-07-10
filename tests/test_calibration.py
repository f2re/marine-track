from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.transform import from_origin, xy

from marine_track.calibration import (
    CalibrationTargets,
    calibration_needed,
    calibration_root,
    create_next_calibration_task,
    labels_path,
    rebuild_calibration_profile,
    score_candidate,
    submit_calibration_answer,
    tasks_dir,
)


def _label(index: int, positive: bool) -> dict[str, object]:
    return {
        "schema_version": 1,
        "label_id": f"label-{index}",
        "candidate_key": f"candidate-{index}",
        "label": "positive" if positive else "negative",
        "features": {
            "peak_score": 0.90 if positive else 0.25,
            "contrast_sigma": 7.0 if positive else 1.0,
            "elongation": 2.5 if positive else 1.1,
            "area_px": 18 if positive else 4,
        },
    }


def test_rebuild_profile_activates_empirical_ranking(tmp_path: Path) -> None:
    calibration_root(tmp_path).mkdir(parents=True)
    records = [_label(index, index < 6) for index in range(12)]
    labels_path(tmp_path).write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    targets = CalibrationTargets(min_labels=10, min_positive=4, min_negative=4)
    profile = rebuild_calibration_profile(tmp_path, targets)

    assert profile["active"] is True
    assert profile["status"] == "ready"
    assert profile["ranking_model"]["kind"] == "logistic"
    assert profile["metrics"]["scope"] == "in_sample_training_only"
    assert calibration_needed(tmp_path, targets) is False
    assert score_candidate(0.9, 7.0, 2.5, profile) > score_candidate(0.25, 1.0, 1.1, profile)


def test_submit_answer_is_idempotent_and_rebuilds_profile(tmp_path: Path) -> None:
    tasks_dir(tmp_path).mkdir(parents=True)
    task = {
        "schema_version": 1,
        "task_id": "task-1",
        "status": "open",
        "candidate_key": "candidate-1",
        "expected_cell": 5,
        "source": {"sensor": "sentinel1"},
        "candidate": {"detection_id": "detection-1"},
        "features": {
            "peak_score": 0.8,
            "contrast_sigma": 5.0,
            "elongation": 2.0,
            "area_px": 12,
        },
    }
    (tasks_dir(tmp_path) / "task-1.json").write_text(json.dumps(task), encoding="utf-8")

    first = submit_calibration_answer(
        tmp_path,
        "task-1",
        admin_id=100,
        answer="5",
        targets=CalibrationTargets(min_labels=4, min_positive=1, min_negative=1),
    )
    second = submit_calibration_answer(
        tmp_path,
        "task-1",
        admin_id=100,
        answer="5",
        targets=CalibrationTargets(min_labels=4, min_positive=1, min_negative=1),
    )

    assert first["record"]["label"] == "positive"
    assert first["profile"]["labels"]["positive"] == 1
    assert second["duplicate"] is True
    assert len(labels_path(tmp_path).read_text(encoding="utf-8").splitlines()) == 1


def test_create_grid_task_from_detection_report(tmp_path: Path) -> None:
    raster_path = tmp_path / "cache" / "scene.tif"
    raster_path.parent.mkdir(parents=True)
    image = np.zeros((300, 300), dtype="float32")
    image[120:124, 140:146] = 20.0
    transform = from_origin(30.0, 50.0, 0.001, 0.001)
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        height=image.shape[0],
        width=image.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(image, 1)

    lon, lat = xy(transform, 122, 143, offset="center")
    report_dir = tmp_path / "detections" / "token-1"
    report_dir.mkdir(parents=True)
    report = {
        "token": "token-1",
        "provider": "test",
        "sensor": "sentinel1",
        "product_id": "product-1",
        "acquisition_time": "2026-07-10T00:00:00+00:00",
        "raster_path": str(raster_path),
        "detections": [
            {
                "detection_id": "candidate-1",
                "lon": lon,
                "lat": lat,
                "confidence": 0.7,
                "validation_status": "unvalidated",
                "metadata": {
                    "peak_score": 0.9,
                    "contrast_sigma": 6.0,
                    "elongation": 2.0,
                    "area_px": 24,
                },
            }
        ],
    }
    (report_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")

    task = create_next_calibration_task(tmp_path, admin_id=100, crop_size_px=384)

    assert task is not None
    assert 1 <= task["expected_cell"] <= 9
    rendered = cv2.imread(task["image_path"])
    assert rendered is not None
    assert rendered.shape[:2] == (384, 384)
