from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box, mapping, shape
from shapely.ops import transform, unary_union

from marine_track.cache_policy import aoi_hash_from_geojson
from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.models import Scene, Sensor
from marine_track.provenance import code_version, package_version, redact_value, sanitize_url
from marine_track.resource_limits import ResourceLimits, validate_geojson_payload
from marine_track.scene_materializer import (
    AssetProbe,
    MaterializationError,
    prepare_asset_access,
    probe_raster_asset,
    select_processing_asset_record,
)
from marine_track.telegram_scene_browser import register_scenes

CANARY_SCHEMA_VERSION = 1
DEFAULT_CANARY_LOOKBACK_HOURS = 168
DEFAULT_CANARY_MAX_RESULTS = 5
DEFAULT_CANARY_SIDE_KM = 8.0
DEFAULT_CANARY_MAX_AREA_KM2 = 100.0
ProgressCallback = Callable[[str], None]


class CanaryMode(str, Enum):
    ASSET = "asset"
    DETECTION = "detection"


class ProviderCanaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class CanaryAOI:
    payload: dict[str, Any]
    source: str
    area_km2: float
    vertex_count: int
    aoi_hash: str
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class ProviderCanaryResult:
    report: dict[str, Any]
    report_path: Path
    detection_result: DetectionRunResult | None = None

    @property
    def ok(self) -> bool:
        return self.report.get("status") == "passed"


def run_provider_canary(
    *,
    mode: CanaryMode | str = CanaryMode.ASSET,
    output_dir: str | Path,
    default_aoi: str | Path,
    base_dir: str | Path = ".",
    explicit_aoi: str | Path | None = None,
    lookback_hours: int | None = None,
    max_results: int | None = None,
    owner_user_id: int = 1,
    owner_chat_id: int = 1,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProviderCanaryResult:
    """Run an operator-triggered Sentinel-1 live canary.

    Asset mode performs provider search, runtime signing/OAuth and a small TIFF
    range-read. Detection mode additionally registers a scoped scene token in an
    isolated self-test state directory, materializes a compact AOI and runs the
    operational detector with wake/Kelvin research explicitly disabled.
    """

    selected_mode = _mode(mode)
    base = Path(base_dir).resolve()
    output = _resolve_path(Path(output_dir), base)
    report_root = output / "selftest"
    report_root.mkdir(parents=True, exist_ok=True)
    os.chmod(report_root, 0o700)

    started_at = _utc(now)
    canary_id = f"{started_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    run_dir = report_root / "runs" / canary_id
    run_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(run_dir, 0o700)
    report_path = run_dir / "report.json"

    hours = _bounded_int(
        lookback_hours,
        "MARINE_TRACK_CANARY_LOOKBACK_HOURS",
        DEFAULT_CANARY_LOOKBACK_HOURS,
        1,
        720,
    )
    result_limit = _bounded_int(
        max_results,
        "MARINE_TRACK_CANARY_MAX_RESULTS",
        DEFAULT_CANARY_MAX_RESULTS,
        1,
        20,
    )
    side_km = _bounded_float(
        None,
        "MARINE_TRACK_CANARY_SIDE_KM",
        DEFAULT_CANARY_SIDE_KM,
        1.0,
        25.0,
    )
    max_area_km2 = _bounded_float(
        None,
        "MARINE_TRACK_CANARY_MAX_AREA_KM2",
        DEFAULT_CANARY_MAX_AREA_KM2,
        1.0,
        625.0,
    )

    report: dict[str, Any] = {
        "schema_version": CANARY_SCHEMA_VERSION,
        "canary_id": canary_id,
        "mode": selected_mode.value,
        "status": "running",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "duration_ms": None,
        "code": {
            "version": code_version(),
            "package_version": package_version(),
        },
        "request": {
            "sensor": Sensor.SENTINEL1.value,
            "lookback_hours": hours,
            "max_results": result_limit,
            "wake_research": False if selected_mode == CanaryMode.DETECTION else None,
        },
        "aoi": None,
        "stages": [],
        "result": {},
        "error": None,
    }
    detection_result: DetectionRunResult | None = None
    start_clock = time.perf_counter()

    try:
        with _stage(report, "aoi", progress_callback) as stage:
            configured_aoi = explicit_aoi or os.getenv("MARINE_TRACK_CANARY_AOI", "").strip() or None
            canary_aoi = build_canary_aoi(
                base_dir=base,
                default_aoi=default_aoi,
                explicit_aoi=configured_aoi,
                side_km=side_km,
                max_area_km2=max_area_km2,
            )
            aoi_path = run_dir / "aoi.geojson"
            _atomic_write_json(aoi_path, canary_aoi.payload, mode=0o600)
            report["aoi"] = {
                "source": canary_aoi.source,
                "hash": canary_aoi.aoi_hash,
                "area_km2": round(canary_aoi.area_km2, 3),
                "vertex_count": canary_aoi.vertex_count,
                "bounds": [round(value, 6) for value in canary_aoi.bounds],
            }
            stage["data"] = {
                "source": canary_aoi.source,
                "area_km2": round(canary_aoi.area_km2, 3),
            }

        end = started_at
        start = end - timedelta(hours=hours)
        with _stage(report, "provider_search", progress_callback) as stage:
            search_result = search_detection_capable_scenes(
                aoi_path,
                start,
                end,
                Sensor.SENTINEL1,
                run_dir / "search",
                result_limit,
            )
            if not search_result.scenes:
                raise ProviderCanaryError("provider search returned no Sentinel-1 scene")
            scene = search_result.scenes[0]
            report["result"]["search"] = {
                "provider": search_result.provider,
                "sensor": search_result.sensor.value,
                "scene_count": len(search_result.scenes),
                "cache_hit": bool(search_result.cache_hit),
                "product_id": scene.product_id,
                "acquisition_time": scene.acquisition_time.isoformat(),
            }
            stage["data"] = {
                "provider": search_result.provider,
                "scene_count": len(search_result.scenes),
                "cache_hit": bool(search_result.cache_hit),
            }

        with _stage(report, "asset_select", progress_callback) as stage:
            selected = select_processing_asset_record(scene)
            if selected is None:
                raise ProviderCanaryError("selected scene has no processable GeoTIFF/COG asset")
            asset_key, asset, asset_href = selected
            stage["data"] = {
                "asset_key": asset_key,
                "media_type": asset.media_type,
                "storage": asset.storage,
                "auth_mode": asset.auth_mode,
            }

        with _stage(report, "asset_access", progress_callback) as stage:
            access_href, headers = prepare_asset_access(
                asset_href,
                search_result.provider,
                asset,
            )
            access_mode = _access_mode(asset_href, access_href, headers)
            probe = probe_raster_asset(access_href, headers=headers)
            asset_payload = _asset_report(
                asset_key=asset_key,
                asset=asset,
                original_href=asset_href,
                access_mode=access_mode,
                probe=probe,
            )
            report["result"]["asset"] = asset_payload
            stage["data"] = {
                "access_mode": access_mode,
                "status": probe.status,
                "range_supported": probe.range_supported,
                "bytes_checked": probe.bytes_checked,
            }

        if selected_mode == CanaryMode.DETECTION:
            if owner_user_id <= 0 or owner_chat_id == 0:
                raise ProviderCanaryError(
                    "detection canary requires non-zero scoped owner user/chat ids"
                )
            state_dir = run_dir / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            os.chmod(state_dir, 0o700)
            with _stage(report, "scoped_registration", progress_callback) as stage:
                tokens = register_scenes(
                    state_dir,
                    search_result.provider,
                    search_result.sensor,
                    [scene],
                    search_result.scenes_json,
                    search_result.asset_manifest,
                    owner_user_id=owner_user_id,
                    owner_chat_id=owner_chat_id,
                    aoi_geojson=canary_aoi.payload,
                    search_hours=hours,
                )
                if len(tokens) != 1:
                    raise ProviderCanaryError("canary scene registration did not return one token")
                scoped_token = tokens[0]
                stage["data"] = {"registered": 1, "scope": "user_and_chat"}

            with _stage(report, "detection", progress_callback) as stage:
                detection_result = run_detection_for_token(
                    token=scoped_token,
                    output_dir=state_dir,
                    owner_user_id=owner_user_id,
                    owner_chat_id=owner_chat_id,
                    max_crops=0,
                    land_mask_geojson=_optional_resolved_path(land_mask_geojson, base),
                    shoreline_buffer_m=shoreline_buffer_m,
                    wake_research=False,
                    progress_callback=(
                        (lambda text: progress_callback(f"detection · {text}"))
                        if progress_callback
                        else None
                    ),
                )
                report["result"]["detection"] = {
                    "candidate_count": len(detection_result.detections),
                    "raster_cache_hit": bool(detection_result.materialized.cache_hit),
                    "aoi_cropped": bool(detection_result.materialized.cropped),
                    "preprocessing_domain": detection_result.preprocessing_plan.output_domain,
                    "calibration_status": detection_result.preprocessing_plan.calibration_status,
                    "wake_research_enabled": bool(detection_result.wake_research_enabled),
                }
                stage["data"] = report["result"]["detection"]
                if detection_result.wake_research_enabled:
                    raise ProviderCanaryError("detection canary must keep wake research disabled")

        report["status"] = "passed"
    except Exception as exc:  # noqa: BLE001 - the canary must persist a failed report
        report["status"] = "failed"
        report["error"] = _safe_error(exc, output)
    finally:
        finished_at = _utc(None)
        report["finished_at"] = finished_at.isoformat()
        report["duration_ms"] = _elapsed_ms(start_clock)
        _write_canary_report(report_path, report, output)
        _write_canary_report(report_root / "latest.json", report, output)

    return ProviderCanaryResult(
        report=report,
        report_path=report_path,
        detection_result=detection_result,
    )


def build_canary_aoi(
    *,
    base_dir: str | Path,
    default_aoi: str | Path,
    explicit_aoi: str | Path | None = None,
    side_km: float = DEFAULT_CANARY_SIDE_KM,
    max_area_km2: float = DEFAULT_CANARY_MAX_AREA_KM2,
) -> CanaryAOI:
    base = Path(base_dir).resolve()
    if not math.isfinite(side_km) or not 1.0 <= side_km <= 25.0:
        raise ProviderCanaryError("canary side_km must be finite and in [1, 25]")
    if not math.isfinite(max_area_km2) or not 1.0 <= max_area_km2 <= 625.0:
        raise ProviderCanaryError("canary max_area_km2 must be finite and in [1, 625]")

    if explicit_aoi:
        source_path = _resolve_path(Path(explicit_aoi), base)
        payload = _read_geojson(source_path)
        source = "explicit_canary_aoi"
    else:
        source_path = _resolve_path(Path(default_aoi), base)
        default_payload = _read_geojson(source_path)
        payload = _compact_aoi_from_payload(default_payload, side_km)
        source = "derived_from_default_aoi"

    metrics = validate_geojson_payload(
        payload,
        limits=ResourceLimits(max_aoi_area_km2=max_area_km2),
    )
    geometry = _polygonal_union(payload)
    return CanaryAOI(
        payload=payload,
        source=source,
        area_km2=metrics.area_km2,
        vertex_count=metrics.vertex_count,
        aoi_hash=aoi_hash_from_geojson(payload),
        bounds=tuple(float(value) for value in geometry.bounds),
    )


def load_latest_canary_report(output_dir: str | Path) -> dict[str, Any] | None:
    path = Path(output_dir) / "selftest" / "latest.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


@contextmanager
def _stage(
    report: dict[str, Any],
    name: str,
    progress_callback: ProgressCallback | None,
):
    stage: dict[str, Any] = {"name": name, "status": "running", "duration_ms": None}
    report["stages"].append(stage)
    if progress_callback:
        progress_callback(name)
    started = time.perf_counter()
    try:
        yield stage
    except Exception as exc:
        stage["status"] = "failed"
        stage["error"] = _safe_error(exc, Path.cwd())
        raise
    else:
        stage["status"] = "passed"
    finally:
        stage["duration_ms"] = _elapsed_ms(started)


def _asset_report(
    *,
    asset_key: str,
    asset: Any,
    original_href: str,
    access_mode: str,
    probe: AssetProbe,
) -> dict[str, Any]:
    return {
        "key": asset_key,
        "media_type": asset.media_type,
        "roles": list(asset.roles),
        "band": asset.band,
        "polarization": asset.polarization,
        "units": asset.units,
        "storage": asset.storage,
        "auth_mode": asset.auth_mode,
        "access_mode": access_mode,
        "endpoint": sanitize_url(original_href),
        "probe": {
            "ok": probe.ok,
            "status": probe.status,
            "content_type": probe.content_type,
            "bytes_checked": probe.bytes_checked,
            "range_supported": probe.range_supported,
        },
    }


def _access_mode(original_href: str, access_href: str, headers: dict[str, str]) -> str:
    if headers:
        return "transient_headers"
    if access_href != original_href:
        return "runtime_signed_url"
    return "public"


def _compact_aoi_from_payload(payload: dict[str, Any], side_km: float) -> dict[str, Any]:
    source = _polygonal_union(payload)
    point = source.representative_point()
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={point.y:.10f} +lon_0={point.x:.10f} +datum=WGS84 +units=m +no_defs"
    )
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_wgs84 = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    source_local = transform(to_local.transform, source)
    centre_local = transform(to_local.transform, point)
    half = side_km * 500.0
    square = box(
        centre_local.x - half,
        centre_local.y - half,
        centre_local.x + half,
        centre_local.y + half,
    )
    clipped = _polygonal_only(source_local.intersection(square))
    if clipped.is_empty:
        raise ProviderCanaryError("default AOI cannot provide a compact polygonal canary sector")
    output = transform(to_wgs84.transform, clipped)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "marine-track-provider-canary"},
                "geometry": mapping(output),
            }
        ],
    }


def _polygonal_union(payload: dict[str, Any]) -> Polygon | MultiPolygon:
    raw: list[dict[str, Any]] = []
    geo_type = payload.get("type")
    if geo_type == "FeatureCollection":
        for feature in payload.get("features") or []:
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict):
                raw.append(feature["geometry"])
    elif geo_type == "Feature" and isinstance(payload.get("geometry"), dict):
        raw.append(payload["geometry"])
    elif isinstance(geo_type, str):
        raw.append(payload)
    geometries = []
    for item in raw:
        parsed = shape(item)
        if parsed.is_empty:
            continue
        if not parsed.is_valid:
            raise ProviderCanaryError("canary AOI geometry is topologically invalid")
        geometries.append(parsed)
    if not geometries:
        raise ProviderCanaryError("canary AOI does not contain geometry")
    merged = _polygonal_only(unary_union(geometries))
    if merged.is_empty:
        raise ProviderCanaryError("canary AOI has no polygonal area")
    return merged


def _polygonal_only(geometry: Any) -> Polygon | MultiPolygon:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons = [item for item in geometry.geoms if isinstance(item, (Polygon, MultiPolygon))]
        if polygons:
            merged = unary_union(polygons)
            if isinstance(merged, (Polygon, MultiPolygon)):
                return merged
    return Polygon()


def _read_geojson(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProviderCanaryError(f"canary AOI file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ProviderCanaryError("canary AOI is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderCanaryError("canary AOI root must be an object")
    return payload


def _mode(value: CanaryMode | str) -> CanaryMode:
    try:
        return value if isinstance(value, CanaryMode) else CanaryMode(str(value).strip().lower())
    except ValueError as exc:
        raise ProviderCanaryError("canary mode must be asset or detection") from exc


def _bounded_int(
    explicit: int | None,
    env_name: str,
    default: int,
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


def _resolve_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def _optional_resolved_path(value: str | Path | None, base_dir: Path) -> Path | None:
    if value is None or not str(value).strip():
        return None
    return _resolve_path(Path(value), base_dir)


def _safe_error(exc: Exception, base_dir: Path) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": _sanitize_text(str(exc), base_dir),
    }


def _sanitize_text(text: str, base_dir: Path) -> str:
    value = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", text)
    value = re.sub(
        r"(?i)(token|secret|password|credential|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[redacted]",
        value,
    )
    value = re.sub(
        r"https?://[^\s<>\"']+",
        lambda match: sanitize_url(match.group(0)),
        value,
    )
    value = re.sub(
        r"(?<![:\w])/(?:[^/\s]+/)+[^/\s:;,]+",
        lambda match: f"<local>/{Path(match.group(0)).name}",
        value,
    )
    sanitized = redact_value(value, base_dir=base_dir)
    return str(sanitized)[:600]


def _write_canary_report(path: Path, report: dict[str, Any], base_dir: Path) -> None:
    sanitized = redact_value(report, base_dir=base_dir)
    _atomic_write_json(path, sanitized, mode=0o600)


def _atomic_write_json(path: Path, payload: dict[str, Any], *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary, mode)
    os.replace(temporary, path)
    os.chmod(path, mode)


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _elapsed_ms(started: float) -> int:
    return max(0, int(round((time.perf_counter() - started) * 1000.0)))
