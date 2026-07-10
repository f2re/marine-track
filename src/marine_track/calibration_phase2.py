from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PHASE2_SCHEMA_VERSION = 2
TASK_GENERATOR_VERSION = "independent-grid-v1"
FEATURE_SET_VERSION = "tile-object-wake-v1"
OBJECT_NONE = "none"
OBJECT_MULTIPLE = "multiple"
OBJECT_UNCERTAIN = "uncertain"
OBJECT_SKIP = "skip"
OBJECT_ANSWERS = {str(index) for index in range(1, 10)} | {
    OBJECT_NONE,
    OBJECT_MULTIPLE,
    OBJECT_UNCERTAIN,
    OBJECT_SKIP,
}
WAKE_NONE = "none"
WAKE_TURBULENT = "turbulent"
WAKE_KELVIN = "kelvin"
WAKE_BOTH = "both"
WAKE_UNCERTAIN = "uncertain"
WAKE_ANSWERS = {WAKE_NONE, WAKE_TURBULENT, WAKE_KELVIN, WAKE_BOTH, WAKE_UNCERTAIN}
HEADING_SECTORS = {"n", "ne", "e", "se", "s", "sw", "w", "nw", "unknown"}
STRATA = ("open_sea", "coastline", "port", "offshore_structure", "high_clutter")


@dataclass(frozen=True)
class Phase2Targets:
    tile_size_px: int = 768
    max_tiles_per_scene: int = 24
    min_valid_fraction: float = 0.85
    min_test_groups: int = 3
    min_validation_groups: int = 3
    min_improvement: float = 0.01
    bootstrap_samples: int = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def phase2_root(output_dir: str | Path) -> Path:
    return Path(output_dir) / "calibration" / "phase2"


def tasks_dir(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "tasks"


def labels_path(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "labels.jsonl"


def manifest_path(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "manifest.json"


def proposed_profile_path(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "proposed_profile.json"


def active_profile_path(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "active_profile.json"


def history_dir(output_dir: str | Path) -> Path:
    return phase2_root(output_dir) / "history"


def assign_split(group_id: str) -> str:
    bucket = int(hashlib.sha256(group_id.encode()).hexdigest()[:8], 16) % 100
    return "train" if bucket < 65 else "calibration" if bucket < 82 else "test"


def scene_group_id(source: dict[str, Any]) -> str:
    orbit = source.get("relative_orbit") or source.get("orbit") or "unknown-orbit"
    acquisition = str(source.get("acquisition_time") or "unknown-time")[:13]
    aoi_hash = source.get("aoi_hash") or source.get("raster_key") or "unknown-aoi"
    sensor = source.get("sensor") or "unknown-sensor"
    fallback = (
        source.get("product_id") or source.get("token") or "unknown-product"
        if orbit == "unknown-orbit" and aoi_hash == "unknown-aoi"
        else ""
    )
    return f"{sensor}|{orbit}|{acquisition}|{aoi_hash}|{fallback}"


def applicability_key(applicability: dict[str, Any], scene_regime: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {**applicability, "scene_regime": scene_regime},
            sort_keys=True,
            ensure_ascii=True,
        ).encode()
    ).hexdigest()[:20]


def submit_object_answer(
    output_dir: str | Path,
    task_id: str,
    admin_id: int,
    answer: str,
) -> dict[str, Any]:
    if answer not in OBJECT_ANSWERS:
        raise ValueError(f"Unsupported object answer: {answer}")
    task = load_phase2_task(output_dir, task_id)
    existing = next(
        (item for item in read_phase2_labels(output_dir) if item.get("task_id") == task_id),
        None,
    )
    if existing:
        return {"task": task, "record": existing, "duplicate": True}
    cell = int(answer) if answer.isdigit() else None
    label = (
        "ship"
        if cell is not None
        else "multiple_ships"
        if answer == OBJECT_MULTIPLE
        else "no_ship"
        if answer == OBJECT_NONE
        else "uncertain"
        if answer == OBJECT_UNCERTAIN
        else "skipped"
    )
    center = _selected_cell_center(task, cell)
    predicted = int(task.get("prediction", {}).get("candidate_count", 0))
    created_at = utc_now()
    record = {
        "schema_version": PHASE2_SCHEMA_VERSION,
        "task_generator_version": TASK_GENERATOR_VERSION,
        "feature_set_version": FEATURE_SET_VERSION,
        "label_id": hashlib.sha256(
            f"{task_id}:{admin_id}:{created_at}".encode()
        ).hexdigest()[:24],
        "created_at": created_at,
        "admin_id": admin_id,
        "task_id": task_id,
        "group_id": task["group_id"],
        "split": task["split"],
        "stratum": task["stratum"],
        "applicability": task["applicability"],
        "applicability_key": task["applicability_key"],
        "object_answer": answer,
        "object_label": label,
        "selected_cell": cell,
        "selected_center": center,
        "localization_error_m": _localization_error_m(task, center),
        "predicted_candidate_count": predicted,
        "max_ranking_score": task.get("prediction", {}).get("max_ranking_score"),
        "tile_area_km2": task.get("tile_area_km2"),
        "missed_target": label in {"ship", "multiple_ships"} and predicted == 0,
        "reference": task.get("reference"),
        "wake": None,
        "source": task.get("source"),
    }
    _append_jsonl(labels_path(output_dir), record)
    return {"task": task, "record": record, "duplicate": False}


def submit_wake_answer(
    output_dir: str | Path,
    task_id: str,
    admin_id: int,
    wake_type: str,
    heading_sector: str = "unknown",
    ambiguity_180: bool = True,
) -> dict[str, Any]:
    if wake_type not in WAKE_ANSWERS:
        raise ValueError(f"Unsupported wake answer: {wake_type}")
    if heading_sector not in HEADING_SECTORS:
        raise ValueError(f"Unsupported heading sector: {heading_sector}")
    records = read_phase2_labels(output_dir)
    for record in records:
        if record.get("task_id") == task_id:
            record["wake"] = {
                "type": wake_type,
                "heading_sector": heading_sector,
                "ambiguity_180": bool(ambiguity_180),
                "annotated_by": admin_id,
                "annotated_at": utc_now(),
            }
            _rewrite_jsonl(labels_path(output_dir), records)
            return record
    raise FileNotFoundError(f"Object label not found for task: {task_id}")


def read_phase2_labels(output_dir: str | Path) -> list[dict[str, Any]]:
    path = labels_path(output_dir)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("schema_version") == PHASE2_SCHEMA_VERSION:
            records.append(payload)
    return records


def load_phase2_task(output_dir: str | Path, task_id: str) -> dict[str, Any]:
    path = tasks_dir(output_dir) / f"{task_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Phase 2 task not found: {task_id}")
    return read_json(path)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        file_obj.flush()
        os.fsync(file_obj.fileno())


def _rewrite_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _selected_cell_center(task: dict[str, Any], cell: int | None) -> dict[str, float] | None:
    if cell is None:
        return None
    window = task["window"]
    row_index, col_index = divmod(cell - 1, 3)
    cell_size = float(window["size_px"]) / 3.0
    return {
        "row": float(window["row0"]) + (row_index + 0.5) * cell_size,
        "col": float(window["col0"]) + (col_index + 0.5) * cell_size,
    }


def _localization_error_m(
    task: dict[str, Any],
    center: dict[str, float] | None,
) -> float | None:
    candidates = task.get("prediction", {}).get("candidates", [])
    if center is None or not candidates:
        return None
    distances = [
        ((float(item["row"]) - center["row"]) ** 2 + (float(item["col"]) - center["col"]) ** 2)
        ** 0.5
        for item in candidates
    ]
    gsd = {
        "lte5m": 5.0,
        "5-15m": 10.0,
        "15-40m": 25.0,
        "gt40m": 50.0,
    }.get(str(task.get("applicability", {}).get("gsd_bucket")))
    return min(distances) * gsd if gsd is not None else None
