from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from marine_track.calibration_phase2 import Phase2Targets
from marine_track.calibration_phase2_tiles import generate_independent_tasks
from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.models import Sensor
from marine_track.telegram_scene_browser import register_scenes, run_dir, utc_window, write_temp_aoi

ProgressCallback = Callable[[str], None]
SESSION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CalibrationPreparationResult:
    processed_tokens: list[str]
    failed_tokens: dict[str, str]
    candidate_count: int
    phase2_task_count: int
    reports: list[Path]
    overviews: list[Path]


def search_sessions_dir(output_dir: str | Path) -> Path:
    return Path(output_dir) / "calibration" / "area_search" / "sessions"


def search_calibration_scenes(
    *,
    output_dir: str | Path,
    area_id: str,
    area_name: str,
    area_source: str,
    aoi_geojson: dict[str, object],
    sensor: Sensor,
    hours: int,
    max_results: int,
    owner_user_id: int,
    owner_chat_id: int,
) -> dict[str, Any]:
    if owner_user_id <= 0 or owner_chat_id == 0:
        raise ValueError("Calibration search requires non-zero Telegram user/chat ids")
    if hours <= 0 or hours > 24 * 30:
        raise ValueError("Calibration search period must be in 1..720 hours")
    if max_results <= 0:
        raise ValueError("max_results must be positive")

    output_dir = Path(output_dir)
    start, end = utc_window(hours)
    aoi_path = write_temp_aoi(aoi_geojson)
    search_dir = run_dir(output_dir, f"calibration_{_safe_id(area_id)}")
    try:
        result = search_detection_capable_scenes(
            aoi_path,
            start,
            end,
            sensor,
            search_dir,
            max_results,
        )
        tokens = register_scenes(
            output_dir,
            result.provider,
            result.sensor,
            result.scenes,
            result.scenes_json,
            result.asset_manifest,
            owner_user_id=owner_user_id,
            owner_chat_id=owner_chat_id,
            aoi_geojson=aoi_geojson,
            search_hours=hours,
        )
    finally:
        aoi_path.unlink(missing_ok=True)

    if not tokens:
        raise RuntimeError("No detection-capable scenes were registered for calibration")

    session_id = hashlib.sha256(
        (
            f"{owner_user_id}|{owner_chat_id}|{area_id}|{sensor.value}|"
            f"{start.isoformat()}|{end.isoformat()}"
        ).encode()
    ).hexdigest()[:16]
    scenes = []
    for token, scene in zip(tokens, result.scenes, strict=False):
        scenes.append(
            {
                "token": token,
                "product_id": scene.product_id,
                "provider": scene.provider,
                "sensor": scene.sensor.value,
                "acquisition_time": scene.acquisition_time.isoformat(),
                "cloud_cover": scene.cloud_cover,
                "polarizations": list(scene.polarizations or []),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "owner_user_id": owner_user_id,
        "owner_chat_id": owner_chat_id,
        "area": {
            "id": area_id,
            "name": area_name,
            "source": area_source,
            "geojson": aoi_geojson,
        },
        "request": {
            "sensor": sensor.value,
            "hours": hours,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "max_results": max_results,
        },
        "result": {
            "provider": result.provider,
            "sensor": result.sensor.value,
            "cache_hit": bool(result.cache_hit),
            "scenes": scenes,
        },
    }
    _atomic_write_json(search_sessions_dir(output_dir) / f"{session_id}.json", payload)
    return payload


def load_search_session(
    output_dir: str | Path,
    session_id: str,
    *,
    owner_user_id: int,
    owner_chat_id: int,
) -> dict[str, Any]:
    path = search_sessions_dir(output_dir) / f"{_safe_id(session_id)}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Calibration search session not found: {session_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Calibration search session is not an object")
    if payload.get("owner_user_id") != owner_user_id or payload.get("owner_chat_id") != owner_chat_id:
        raise PermissionError("Calibration search session belongs to another user/chat")
    return payload


def session_tokens(session: dict[str, Any], limit: int | None = None) -> list[str]:
    result = session.get("result") if isinstance(session.get("result"), dict) else {}
    scenes = result.get("scenes") if isinstance(result.get("scenes"), list) else []
    tokens = [str(item.get("token")) for item in scenes if isinstance(item, dict) and item.get("token")]
    return tokens if limit is None else tokens[: max(0, int(limit))]


def prepare_calibration_data(
    *,
    output_dir: str | Path,
    tokens: Iterable[str],
    owner_user_id: int,
    owner_chat_id: int,
    max_crops: int,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float,
    phase2_targets: Phase2Targets,
    context_geojson: str | Path | None = None,
    progress_callback: ProgressCallback | None = None,
) -> CalibrationPreparationResult:
    output_dir = Path(output_dir)
    unique_tokens = list(dict.fromkeys(str(token) for token in tokens if str(token)))
    processed: list[str] = []
    failed: dict[str, str] = {}
    candidate_count = 0
    reports: list[Path] = []
    overviews: list[Path] = []

    for index, token in enumerate(unique_tokens, start=1):
        _progress(progress_callback, f"scene {index}/{len(unique_tokens)} · prepare")
        try:
            result: DetectionRunResult = run_detection_for_token(
                token=token,
                output_dir=output_dir,
                owner_user_id=owner_user_id,
                owner_chat_id=owner_chat_id,
                max_crops=max_crops,
                land_mask_geojson=land_mask_geojson,
                shoreline_buffer_m=shoreline_buffer_m,
                progress_callback=(
                    lambda stage, current=index: _progress(
                        progress_callback,
                        f"scene {current}/{len(unique_tokens)} · {stage}",
                    )
                ),
            )
        except Exception as exc:  # noqa: BLE001 - batch must continue with other scenes
            failed[token] = f"{type(exc).__name__}: {exc}"
            continue
        processed.append(token)
        candidate_count += len(result.detections)
        reports.append(result.report_json)
        overviews.append(result.overview_png)

    if not processed:
        details = "; ".join(failed.values()) or "no tokens"
        raise RuntimeError(f"No calibration scene was processed: {details}")

    _progress(progress_callback, "phase 2 · generating independent tiles")
    manifest = generate_independent_tasks(
        output_dir,
        phase2_targets,
        Path(context_geojson) if context_geojson else None,
    )
    tasks = manifest.get("tasks") if isinstance(manifest.get("tasks"), list) else []
    return CalibrationPreparationResult(
        processed_tokens=processed,
        failed_tokens=failed,
        candidate_count=candidate_count,
        phase2_task_count=len(tasks),
        reports=reports,
        overviews=overviews,
    )


def _progress(callback: ProgressCallback | None, text: str) -> None:
    if callback is not None:
        callback(text)


def _safe_id(value: str) -> str:
    cleaned = "".join(character for character in str(value) if character.isalnum() or character in "_-")
    if not cleaned:
        raise ValueError("Identifier is empty after normalization")
    return cleaned[:80]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
