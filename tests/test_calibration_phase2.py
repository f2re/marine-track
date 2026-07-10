from __future__ import annotations

import json
from pathlib import Path

from marine_track.calibration_phase2 import (
    PHASE2_SCHEMA_VERSION,
    Phase2Targets,
    assign_split,
    labels_path,
    submit_object_answer,
    submit_wake_answer,
    tasks_dir,
)
from marine_track.calibration_phase2_evaluation import (
    active_post_filter_threshold,
    promote_proposed_profile,
    rollback_profile,
)


def _write_task(output_dir: Path, task_id: str = "task-1") -> None:
    task = {
        "schema_version": PHASE2_SCHEMA_VERSION,
        "task_id": task_id,
        "group_id": "scene-group",
        "split": "test",
        "stratum": "open_sea",
        "applicability": {"sensor": "sentinel1", "gsd_bucket": "5-15m"},
        "applicability_key": "app-key",
        "window": {"row0": 0, "col0": 0, "size_px": 900},
        "prediction": {
            "candidate_count": 0,
            "max_ranking_score": None,
            "candidates": [],
        },
        "reference": {"ais_status": "unavailable", "ground_truth": False},
        "tile_area_km2": 81.0,
        "source": {"product_id": "scene-1"},
    }
    path = tasks_dir(output_dir) / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(task), encoding="utf-8")


def _groups(split: str, count: int) -> list[str]:
    result: list[str] = []
    index = 0
    while len(result) < count:
        value = f"group-{split}-{index}"
        if assign_split(value) == split:
            result.append(value)
        index += 1
    return result


def _write_records(output_dir: Path, suffix: str = "a") -> None:
    records = []
    for split in ("calibration", "test"):
        for index, group in enumerate(_groups(split, 2)):
            truth = index % 2 == 0
            records.append(
                {
                    "schema_version": PHASE2_SCHEMA_VERSION,
                    "label_id": f"{suffix}-{split}-{index}",
                    "task_id": f"{suffix}-{split}-{index}",
                    "group_id": group,
                    "split": split,
                    "stratum": "open_sea",
                    "applicability": {"sensor": "sentinel1", "gsd_bucket": "5-15m"},
                    "applicability_key": "app-key",
                    "object_label": "ship" if truth else "no_ship",
                    "predicted_candidate_count": 1 if truth else 0,
                    "max_ranking_score": 0.9 if truth else 0.1,
                    "tile_area_km2": 10.0,
                    "missed_target": False,
                    "wake": None,
                }
            )
    path = labels_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file_obj:
        for record in records:
            file_obj.write(json.dumps(record) + "\n")


def test_assign_split_is_stable_for_scene_group():
    group = "sentinel1|42|2026-07-10T07|aoi"
    assert assign_split(group) == assign_split(group)


def test_object_and_wake_annotation(tmp_path):
    _write_task(tmp_path)
    result = submit_object_answer(tmp_path, "task-1", admin_id=100, answer="5")
    assert result["record"]["object_label"] == "ship"
    assert result["record"]["missed_target"] is True
    record = submit_wake_answer(
        tmp_path,
        "task-1",
        admin_id=100,
        wake_type="kelvin",
        heading_sector="ne",
        ambiguity_180=True,
    )
    assert record["wake"]["type"] == "kelvin"
    assert record["wake"]["heading_sector"] == "ne"
    assert record["wake"]["ambiguity_180"] is True


def test_promotion_gate_and_rollback(tmp_path):
    _write_records(tmp_path, "first")
    targets = Phase2Targets(
        min_test_groups=1,
        min_validation_groups=1,
        min_improvement=0.0,
        bootstrap_samples=20,
    )
    first = promote_proposed_profile(tmp_path, targets)
    threshold, profile_id = active_post_filter_threshold(tmp_path)
    assert threshold is not None
    assert profile_id == first["profile_id"]

    _write_records(tmp_path, "second")
    second = promote_proposed_profile(tmp_path, targets)
    assert second["profile_id"] != first["profile_id"]

    restored = rollback_profile(tmp_path, first["profile_id"])
    assert restored["profile_id"] == first["profile_id"]
    assert active_post_filter_threshold(tmp_path)[1] == first["profile_id"]
