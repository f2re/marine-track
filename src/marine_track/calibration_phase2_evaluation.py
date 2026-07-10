from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from marine_track.calibration_phase2 import (
    FEATURE_SET_VERSION,
    PHASE2_SCHEMA_VERSION,
    TASK_GENERATOR_VERSION,
    Phase2Targets,
    active_profile_path,
    atomic_write_json,
    history_dir,
    phase2_root,
    proposed_profile_path,
    read_json,
    read_phase2_labels,
    utc_now,
)


def evaluate_phase2(
    output_dir: str | Path,
    bootstrap_samples: int = 300,
) -> dict[str, Any]:
    records = [
        item
        for item in read_phase2_labels(output_dir)
        if item.get("object_label") not in {"uncertain", "skipped"}
    ]
    split_metrics = {
        split: _metrics([item for item in records if item.get("split") == split])
        for split in ("train", "calibration", "test")
    }
    by_applicability: dict[str, Any] = {}
    for key in sorted({str(item.get("applicability_key")) for item in records}):
        subset = [item for item in records if str(item.get("applicability_key")) == key]
        by_applicability[key] = {
            "applicability": subset[0].get("applicability") if subset else {},
            "metrics": _metrics(subset),
        }
    bootstrap = _bootstrap_group_metrics(
        [item for item in records if item.get("split") == "test"],
        samples=bootstrap_samples,
    )
    result = {
        "schema_version": PHASE2_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "label_count": len(records),
        "groups": len({item.get("group_id") for item in records}),
        "splits": split_metrics,
        "by_applicability": by_applicability,
        "test_bootstrap_ci95": bootstrap,
        "notes": [
            "AIS is stored as reference quality metadata and is not unconditional ground truth.",
            "Wake labels are evaluated separately from object detection.",
            "ranking_score is not a calibrated probability.",
        ],
    }
    atomic_write_json(phase2_root(output_dir) / "evaluation.json", result)
    return result


def build_proposed_profile(
    output_dir: str | Path,
    targets: Phase2Targets | None = None,
) -> dict[str, Any]:
    targets = targets or Phase2Targets()
    evaluation = evaluate_phase2(output_dir, targets.bootstrap_samples)
    records = read_phase2_labels(output_dir)
    calibration_records = [
        item
        for item in records
        if item.get("split") == "calibration"
        and item.get("object_label") not in {"uncertain", "skipped"}
    ]
    threshold = _select_score_threshold(calibration_records)
    profile = {
        "schema_version": PHASE2_SCHEMA_VERSION,
        "profile_id": hashlib.sha256(
            json.dumps(
                sorted(str(item.get("label_id")) for item in records),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()[:16],
        "created_at": utc_now(),
        "status": "proposed",
        "task_generator_version": TASK_GENERATOR_VERSION,
        "feature_set_version": FEATURE_SET_VERSION,
        "applicability_profiles": evaluation["by_applicability"],
        "post_filter": {
            "ranking_score_threshold": threshold,
            "applied_automatically": False,
        },
        "cfar": {
            "applied_automatically": False,
            "threshold_sigma": None,
            "local_window_px": None,
            "guard_window_px": None,
            "note": "CFAR changes require held-out improvement and explicit promotion.",
        },
        "evaluation": evaluation,
        "promotion_gate": _promotion_gate(Path(output_dir), evaluation, targets),
    }
    atomic_write_json(proposed_profile_path(output_dir), profile)
    return profile


def promote_proposed_profile(
    output_dir: str | Path,
    targets: Phase2Targets | None = None,
) -> dict[str, Any]:
    targets = targets or Phase2Targets()
    profile = build_proposed_profile(output_dir, targets)
    gate = profile["promotion_gate"]
    if not gate.get("passed"):
        raise ValueError(
            "Calibration profile promotion gate failed: "
            + "; ".join(gate.get("reasons", []))
        )
    active_path = active_profile_path(output_dir)
    if active_path.is_file():
        current = read_json(active_path)
        history_dir(output_dir).mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            history_dir(output_dir) / f"{current.get('profile_id', 'unknown')}.json",
            current,
        )
    profile["status"] = "active"
    profile["activated_at"] = utc_now()
    atomic_write_json(active_path, profile)
    return profile


def rollback_profile(output_dir: str | Path, profile_id: str | None = None) -> dict[str, Any]:
    history = sorted(
        history_dir(output_dir).glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if profile_id:
        history = [path for path in history if path.stem == profile_id]
    if not history:
        raise FileNotFoundError("No calibration profile available for rollback")
    selected = read_json(history[0])
    active = active_profile_path(output_dir)
    if active.is_file():
        current = read_json(active)
        atomic_write_json(
            history_dir(output_dir) / f"{current.get('profile_id', 'unknown')}.json",
            current,
        )
    selected["status"] = "active"
    selected["rolled_back_at"] = utc_now()
    atomic_write_json(active, selected)
    return selected


def load_active_phase2_profile(output_dir: str | Path) -> dict[str, Any] | None:
    path = active_profile_path(output_dir)
    if not path.is_file():
        return None
    try:
        profile = read_json(path)
    except (OSError, ValueError):
        return None
    if profile.get("schema_version") != PHASE2_SCHEMA_VERSION or profile.get("status") != "active":
        return None
    return profile


def active_post_filter_threshold(output_dir: str | Path) -> tuple[float | None, str | None]:
    profile = load_active_phase2_profile(output_dir)
    if not profile:
        return None, None
    threshold = profile.get("post_filter", {}).get("ranking_score_threshold")
    if not isinstance(threshold, (int, float)):
        return None, str(profile.get("profile_id") or "")
    return float(threshold), str(profile.get("profile_id") or "")


def _promotion_gate(
    output_dir: Path,
    evaluation: dict[str, Any],
    targets: Phase2Targets,
) -> dict[str, Any]:
    reasons: list[str] = []
    validation = evaluation["splits"]["calibration"]
    test = evaluation["splits"]["test"]
    if int(validation.get("groups", 0)) < targets.min_validation_groups:
        reasons.append("insufficient calibration groups")
    if int(test.get("groups", 0)) < targets.min_test_groups:
        reasons.append("insufficient test groups")
    active_path = active_profile_path(output_dir)
    baseline_f1 = 0.0
    baseline_recall = 0.0
    if active_path.is_file():
        active = read_json(active_path)
        baseline_test = (
            active.get("evaluation", {}).get("splits", {}).get("test", {})
            if isinstance(active.get("evaluation"), dict)
            else {}
        )
        baseline_f1 = float(baseline_test.get("f1", 0.0))
        baseline_recall = float(baseline_test.get("recall", 0.0))
    if float(test.get("f1", 0.0)) < baseline_f1 + targets.min_improvement:
        reasons.append("test F1 does not improve baseline")
    if float(test.get("recall", 0.0)) + 1e-12 < baseline_recall:
        reasons.append("test recall regressed")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "baseline_f1": baseline_f1,
        "baseline_recall": baseline_recall,
        "required_improvement": targets.min_improvement,
    }


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups = len({item.get("group_id") for item in records})
    tp = fp = fn = tn = 0
    area_negative = 0.0
    localization: list[float] = []
    for item in records:
        truth = item.get("object_label") in {"ship", "multiple_ships"}
        predicted = int(item.get("predicted_candidate_count", 0)) > 0
        if truth and predicted:
            tp += 1
        elif truth and not predicted:
            fn += 1
        elif not truth and predicted:
            fp += 1
        else:
            tn += 1
        if not truth:
            area_negative += float(item.get("tile_area_km2") or 0.0)
        error = item.get("localization_error_m")
        if isinstance(error, (int, float)) and math.isfinite(float(error)):
            localization.append(float(error))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-12, precision + recall)
    far = fp / max(1, tp + fp)
    csi = tp / max(1, tp + fp + fn)
    return {
        "count": len(records),
        "groups": groups,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "pod": recall,
        "far": far,
        "f1": f1,
        "csi": csi,
        "false_alarms_per_km2": fp / max(area_negative, 1e-12),
        "localization_mae_m": float(np.mean(localization)) if localization else None,
        "localization_p95_m": float(np.percentile(localization, 95)) if localization else None,
        "missed_targets": sum(bool(item.get("missed_target")) for item in records),
    }


def _bootstrap_group_metrics(records: list[dict[str, Any]], samples: int) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record.get("group_id"))].append(record)
    keys = sorted(grouped)
    if len(keys) < 2 or samples <= 0:
        return {}
    rng = np.random.default_rng(20260710)
    values: dict[str, list[float]] = defaultdict(list)
    for _ in range(samples):
        sampled = rng.choice(keys, size=len(keys), replace=True)
        subset = [item for key in sampled for item in grouped[str(key)]]
        metrics = _metrics(subset)
        for name in ("precision", "recall", "f1", "far", "csi", "false_alarms_per_km2"):
            values[name].append(float(metrics[name]))
    return {
        name: {
            "low": float(np.percentile(series, 2.5)),
            "median": float(np.percentile(series, 50)),
            "high": float(np.percentile(series, 97.5)),
        }
        for name, series in values.items()
    }


def _select_score_threshold(records: list[dict[str, Any]]) -> float | None:
    scored = [
        item
        for item in records
        if isinstance(item.get("max_ranking_score"), (int, float))
    ]
    if not scored:
        return None
    candidates = sorted(
        {
            0.0,
            0.25,
            0.5,
            0.75,
            1.0,
            *(float(item["max_ranking_score"]) for item in scored),
        }
    )
    best = (float("-inf"), 0.5)
    for threshold in candidates:
        transformed = [
            {
                **item,
                "predicted_candidate_count": int(
                    float(item["max_ranking_score"]) >= threshold
                ),
            }
            for item in scored
        ]
        metrics = _metrics(transformed)
        objective = 0.7 * float(metrics["f1"]) + 0.3 * float(metrics["csi"])
        if objective > best[0] or (
            math.isclose(objective, best[0]) and threshold > best[1]
        ):
            best = (objective, threshold)
    return float(best[1])
