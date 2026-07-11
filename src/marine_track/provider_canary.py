from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Literal

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import unary_union

from marine_track.cache_policy import aoi_hash_from_geojson
from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.models import SceneAsset, Sensor
from marine_track.provenance import code_version, safe_path_reference, sanitize_url, write_redacted_json
from marine_track.resource_limits import validate_geojson_payload
from marine_track.scene_materializer import (
    AssetProbe,
    prepare_asset_access,
    probe_raster_asset,
    select_processing_asset_record,
)
from marine_track.telegram_scene_browser import register_scenes

CanaryMode = Literal["asset", "detection"]
ProgressCallback = Callable[[str], None]
_URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<![\w:])/(?:[^\s/]+/)+[^\s]+")
_SECRET_NAME_PATTERN = re.compile(
    r"(token|secret|password|credential|authorization|signature|api[_-]?key)",
    re.IGNORECASE,
)


class ProviderCanaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanaryRunResult:
    report: dict[str, Any]
    report_path: Path


@dataclass(frozen=True)
class _StageResult:
    value: Any
    data: dict[str, Any]
    detail: str = "ok"


def run_sentinel1_canary(
    *,
    output_dir: str | Path,
    default_aoi: str | Path,
    mode: CanaryMode = "asset",
    canary_aoi: str | Path | None = None,
    lookback_hours: int | None = None,
    max_results: int | None = None,
    span_deg: float | None = None,
    owner_user_id: int | None = None,
    owner_chat_id: int | None = None,
    confirm_detection: bool = False,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    progress_callback: ProgressCallback | None = None,
) -> CanaryRunResult:
    """Run an explicit, redacted Sentinel-1 provider canary.

    ``asset`` mode performs AOI construction, provider search, runtime signing/OAuth
    and a TIFF range-read probe. ``detection`` additionally materializes one compact
    scene and runs the detector with wake research forcibly disabled. No canary is
    invoked automatically by startup or deployment.
    """

    normalized_mode = str(mode).strip().lower()
    output_root = Path(output_dir)
    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%S%fZ')}-{secrets.token_hex(3)}"
    run_dir = output_root / "selftest" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    _chmod(run_dir, 0o700)
    report_path = run_dir / "report.json"
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "mode": normalized_mode,
        "status": "running",
        "sensor": Sensor.SENTINEL1.value,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "code_version": code_version(),
        "release_id": os.getenv("MARINE_TRACK_RELEASE_ID", "unknown") or "unknown",
        "stages": [],
        "aoi": None,
        "scene": None,
        "asset": None,
        "detection": None,
        "error": None,
    }

    try:
        if normalized_mode not in {"asset", "detection"}:
            raise ProviderCanaryError("mode must be asset or detection")
        if normalized_mode == "detection":
            if not confirm_detection:
                raise ProviderCanaryError(
                    "detection mode requires explicit confirmation before provider quota is used"
                )
            if not owner_user_id or owner_user_id <= 0 or not owner_chat_id:
                raise ProviderCanaryError(
                    "detection mode requires non-zero owner_user_id and owner_chat_id"
                )

        effective_lookback = _bounded_int(
            lookback_hours,
            "MARINE_TRACK_CANARY_LOOKBACK_HOURS",
            336,
            minimum=1,
            maximum=720,
        )
        effective_max_results = _bounded_int(
            max_results,
            "MARINE_TRACK_CANARY_MAX_RESULTS",
            3,
            minimum=1,
            maximum=10,
        )
        effective_span = _bounded_float(
            span_deg,
            "MARINE_TRACK_CANARY_SPAN_DEG",
            0.10,
            minimum=0.02,
            maximum=0.25,
        )

        source_path, source_kind = _resolve_aoi_source(default_aoi, canary_aoi)
        aoi_stage = _run_stage(
            report,
            "aoi",
            progress_callback,
            lambda: _prepare_compact_aoi(
                source_path=source_path,
                source_kind=source_kind,
                destination=run_dir / "aoi.geojson",
                span_deg=effective_span,
            ),
        )
        aoi_path, aoi_payload = aoi_stage.value
        report["aoi"] = aoi_stage.data

        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=effective_lookback)
        search_stage = _run_stage(
            report,
            "search",
            progress_callback,
            lambda: _search_stage(
                aoi_path=aoi_path,
                output=run_dir / "search",
                start=start,
                end=end,
                max_results=effective_max_results,
            ),
        )
        search_result = search_stage.value
        if not search_result.scenes:
            raise ProviderCanaryError("provider search returned no detection-capable Sentinel-1 scene")
        scene = search_result.scenes[0]
        report["scene"] = {
            "provider": search_result.provider,
            "product_id": scene.product_id,
            "acquisition_time": scene.acquisition_time.isoformat(),
            "polarizations": list(scene.polarizations or []),
            "search_cache_hit": bool(search_result.cache_hit),
        }

        selection_stage = _run_stage(
            report,
            "asset_select",
            progress_callback,
            lambda: _select_asset(scene),
        )
        asset_key, asset, href = selection_stage.value

        probe_stage = _run_stage(
            report,
            "asset_probe",
            progress_callback,
            lambda: _probe_asset(search_result.provider, asset_key, asset, href),
        )
        report["asset"] = probe_stage.data

        if normalized_mode == "detection":
            detection_stage = _run_stage(
                report,
                "detection",
                progress_callback,
                lambda: _detection_stage(
                    output_dir=output_root,
                    search_result=search_result,
                    scene=scene,
                    aoi_payload=aoi_payload,
                    lookback_hours=effective_lookback,
                    owner_user_id=int(owner_user_id),
                    owner_chat_id=int(owner_chat_id),
                    land_mask_geojson=land_mask_geojson,
                    shoreline_buffer_m=shoreline_buffer_m,
                ),
            )
            report["detection"] = detection_stage.data

        report["status"] = "success"
    except Exception as exc:  # noqa: BLE001 - canary must always persist a report
        report["status"] = "failed"
        report["error"] = {
            "type": type(exc).__name__,
            "message": safe_error_message(exc),
        }
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_redacted_json(report_path, report, base_dir=output_root)
        _chmod(report_path, 0o600)

    return CanaryRunResult(report=report, report_path=report_path)


def compact_canary_aoi(
    payload: dict[str, Any],
    *,
    span_deg: float = 0.10,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not math.isfinite(span_deg) or not 0.02 <= span_deg <= 0.25:
        raise ProviderCanaryError("canary span_deg must be finite and in [0.02, 0.25]")
    raw_geometries = _extract_geometries(payload)
    if not raw_geometries:
        raise ProviderCanaryError("canary AOI contains no geometry")
    geometries = []
    for raw in raw_geometries:
        geometry = shape(raw)
        if not geometry.is_empty:
            geometries.append(geometry)
    if not geometries:
        raise ProviderCanaryError("canary AOI geometry is empty")
    merged = unary_union(geometries)
    if not merged.is_valid:
        raise ProviderCanaryError("canary AOI geometry is topologically invalid")

    center = merged.representative_point()
    half = span_deg / 2.0
    west = max(-180.0, float(center.x) - half)
    east = min(180.0, float(center.x) + half)
    south = max(-90.0, float(center.y) - half)
    north = min(90.0, float(center.y) + half)
    clipped = merged.intersection(box(west, south, east, north))
    polygonal = _polygonal(clipped)
    if polygonal.is_empty:
        raise ProviderCanaryError("unable to derive a compact polygonal canary AOI")
    compact = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"purpose": "marine_track_provider_canary"},
                "geometry": mapping(polygonal),
            }
        ],
    }
    metrics = validate_geojson_payload(compact)
    bounds = polygonal.bounds
    metadata = {
        "hash": aoi_hash_from_geojson(compact),
        "area_km2": round(metrics.area_km2, 3),
        "vertex_count": metrics.vertex_count,
        "geometry_count": metrics.geometry_count,
        "bbox": [round(float(value), 6) for value in bounds],
        "span_deg": span_deg,
    }
    return compact, metadata


def safe_error_message(error: BaseException) -> str:
    text = str(error) or type(error).__name__
    for name, value in os.environ.items():
        if value and len(value) >= 6 and _SECRET_NAME_PATTERN.search(name):
            text = text.replace(value, "[redacted]")

    def replace_url(match: re.Match[str]) -> str:
        value = match.group(0).rstrip(".,;:)]}")
        suffix = match.group(0)[len(value) :]
        return sanitize_url(value) + suffix

    text = _URL_PATTERN.sub(replace_url, text)
    text = _ABSOLUTE_PATH_PATTERN.sub("<local-path>", text)
    text = " ".join(text.split())
    return text[:500]


def _prepare_compact_aoi(
    *,
    source_path: Path,
    source_kind: str,
    destination: Path,
    span_deg: float,
) -> _StageResult:
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProviderCanaryError("configured canary AOI is not available") from exc
    except json.JSONDecodeError as exc:
        raise ProviderCanaryError("configured canary AOI is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderCanaryError("configured canary AOI must be a GeoJSON object")
    compact, metadata = compact_canary_aoi(payload, span_deg=span_deg)
    _write_private_json(destination, compact)
    metadata["source"] = source_kind
    return _StageResult(value=(destination, compact), data=metadata)


def _search_stage(
    *,
    aoi_path: Path,
    output: Path,
    start: datetime,
    end: datetime,
    max_results: int,
) -> _StageResult:
    result = search_detection_capable_scenes(
        aoi_path,
        start,
        end,
        Sensor.SENTINEL1,
        output,
        max_results,
    )
    return _StageResult(
        value=result,
        data={
            "provider": result.provider,
            "scene_count": len(result.scenes),
            "cache_hit": bool(result.cache_hit),
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
        },
    )


def _select_asset(scene: Any) -> _StageResult:
    selected = select_processing_asset_record(scene)
    if selected is None:
        raise ProviderCanaryError("selected scene has no processable typed GeoTIFF/COG asset")
    asset_key, asset, href = selected
    return _StageResult(
        value=(asset_key, asset, href),
        data={
            "asset_key": asset_key,
            "media_type": asset.media_type,
            "roles": list(asset.roles),
            "polarization": asset.polarization,
            "band": asset.band,
            "units": asset.units,
            "storage": asset.storage,
            "auth_mode": asset.auth_mode,
        },
    )


def _probe_asset(
    provider: str,
    asset_key: str,
    asset: SceneAsset,
    href: str,
) -> _StageResult:
    access_href, headers = prepare_asset_access(href, provider, asset)
    probe: AssetProbe = probe_raster_asset(access_href, headers=headers)
    return _StageResult(
        value=probe,
        data={
            "asset_key": asset_key,
            "media_type": asset.media_type or probe.content_type,
            "roles": list(asset.roles),
            "polarization": asset.polarization,
            "band": asset.band,
            "units": asset.units,
            "storage": asset.storage,
            "auth_mode": asset.auth_mode,
            "probe": {
                "ok": probe.ok,
                "http_status": probe.status,
                "content_type": probe.content_type,
                "bytes_checked": probe.bytes_checked,
                "range_supported": probe.range_supported,
            },
        },
    )


def _detection_stage(
    *,
    output_dir: Path,
    search_result: Any,
    scene: Any,
    aoi_payload: dict[str, Any],
    lookback_hours: int,
    owner_user_id: int,
    owner_chat_id: int,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float,
) -> _StageResult:
    tokens = register_scenes(
        output_dir,
        search_result.provider,
        search_result.sensor,
        [scene],
        search_result.scenes_json,
        search_result.asset_manifest,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
        aoi_geojson=aoi_payload,
        search_hours=lookback_hours,
    )
    if not tokens:
        raise ProviderCanaryError("canary scene registry did not produce a scoped token")
    detection: DetectionRunResult = run_detection_for_token(
        token=tokens[0],
        output_dir=output_dir,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
        max_crops=0,
        land_mask_geojson=land_mask_geojson,
        shoreline_buffer_m=shoreline_buffer_m,
        wake_enabled_override=False,
    )
    return _StageResult(
        value=detection,
        data={
            "candidate_count": len(detection.detections),
            "wake_research_enabled": detection.wake_research_enabled,
            "aoi_cropped": bool(detection.materialized.cropped),
            "raster_cache_hit": bool(detection.materialized.cache_hit),
            "result_report": safe_path_reference(detection.report_json, output_dir),
            "overview": safe_path_reference(detection.overview_png, output_dir),
        },
    )


def _run_stage(
    report: dict[str, Any],
    name: str,
    callback: ProgressCallback | None,
    operation: Callable[[], _StageResult],
) -> _StageResult:
    _progress(callback, name)
    started = perf_counter()
    try:
        result = operation()
    except Exception as exc:
        report["stages"].append(
            {
                "name": name,
                "status": "failed",
                "duration_ms": round((perf_counter() - started) * 1000),
                "detail": type(exc).__name__,
            }
        )
        raise
    report["stages"].append(
        {
            "name": name,
            "status": "ok",
            "duration_ms": round((perf_counter() - started) * 1000),
            "detail": result.detail,
        }
    )
    return result


def _resolve_aoi_source(
    default_aoi: str | Path,
    explicit_aoi: str | Path | None,
) -> tuple[Path, str]:
    if explicit_aoi is not None:
        return Path(explicit_aoi), "explicit_argument"
    configured = os.getenv("MARINE_TRACK_CANARY_AOI", "").strip()
    if configured:
        return Path(configured), "configured_canary_aoi"
    return Path(default_aoi), "compact_default_aoi"


def _extract_geometries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    kind = payload.get("type")
    if kind == "FeatureCollection":
        features = payload.get("features")
        if not isinstance(features, list):
            return []
        return [
            feature["geometry"]
            for feature in features
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
        ]
    if kind == "Feature":
        geometry = payload.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    return [payload] if isinstance(kind, str) else []


def _polygonal(geometry: Any) -> Any:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon))]
        return unary_union(parts) if parts else Polygon()
    return Polygon()


def _bounded_int(
    explicit: int | None,
    env_name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw: Any = explicit if explicit is not None else os.getenv(env_name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderCanaryError(f"{env_name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ProviderCanaryError(f"{env_name} must be in [{minimum}, {maximum}]")
    return value


def _bounded_float(
    explicit: float | None,
    env_name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw: Any = explicit if explicit is not None else os.getenv(env_name, str(default))
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ProviderCanaryError(f"{env_name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ProviderCanaryError(f"{env_name} must be finite and in [{minimum}, {maximum}]")
    return value


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _chmod(temporary, 0o600)
    os.replace(temporary, path)
    _chmod(path, 0o600)


def _progress(callback: ProgressCallback | None, stage: str) -> None:
    if callback is not None:
        callback(stage)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        pass
