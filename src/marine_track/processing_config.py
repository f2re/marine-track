from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from marine_track.models import Sensor

PROCESSING_CONFIG_SCHEMA_VERSION = 2
DEFAULT_PROCESSING_CONFIG = Path("config/processing.yaml")


@dataclass(frozen=True)
class EffectiveDetectorConfig:
    schema_version: int
    sensor: str
    domain: str
    method: str
    threshold_sigma: float
    min_area_px: int
    max_area_px: int
    local_window_px: int
    guard_window_px: int
    min_contrast_sigma: float
    min_training_fraction: float
    tile_size_px: int
    tile_overlap_px: int
    normalization_sample_pixels: int
    max_raster_pixels: int
    max_tiles: int
    max_candidates: int
    max_aoi_area_km2: float
    max_aoi_vertices: int
    preprocessing: dict[str, Any]
    source_path: str
    config_hash: str

    def detector_kwargs(self) -> dict[str, int | float]:
        return {
            "threshold_sigma": self.threshold_sigma,
            "min_area_px": self.min_area_px,
            "max_area_px": self.max_area_px,
            "local_window_px": self.local_window_px,
            "guard_window_px": self.guard_window_px,
            "min_contrast_sigma": self.min_contrast_sigma,
            "min_training_fraction": self.min_training_fraction,
            "tile_size_px": self.tile_size_px,
            "tile_overlap_px": self.tile_overlap_px,
            "normalization_sample_pixels": self.normalization_sample_pixels,
            "max_raster_pixels": self.max_raster_pixels,
            "max_tiles": self.max_tiles,
            "max_candidates": self.max_candidates,
        }

    def as_report_dict(self) -> dict[str, Any]:
        return asdict(self)


def processing_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.getenv("MARINE_TRACK_PROCESSING_CONFIG", str(DEFAULT_PROCESSING_CONFIG)))


def canonical_sensor(value: Sensor | str) -> Sensor:
    if isinstance(value, Sensor):
        if value == Sensor.AUTO:
            raise ValueError("effective processing config requires a concrete sensor")
        return value
    normalized = str(value).strip().lower().replace("-", "")
    aliases = {
        "s1": Sensor.SENTINEL1,
        "sentinel1": Sensor.SENTINEL1,
        "sar": Sensor.SENTINEL1,
        "s2": Sensor.SENTINEL2,
        "sentinel2": Sensor.SENTINEL2,
        "optical": Sensor.SENTINEL2,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported concrete sensor for processing config: {value!r}") from exc


def load_processing_yaml(path: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved = processing_config_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Processing config not found: {resolved}")
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Processing config must be a mapping: {resolved}")
    return resolved, payload


def load_effective_detector_config(
    sensor: Sensor | str,
    *,
    path: str | Path | None = None,
    threshold_sigma: float | None = None,
    min_area_px: int | None = None,
    max_area_px: int | None = None,
    local_window_px: int | None = None,
    guard_window_px: int | None = None,
    min_contrast_sigma: float | None = None,
    min_training_fraction: float | None = None,
    tile_size_px: int | None = None,
    tile_overlap_px: int | None = None,
    normalization_sample_pixels: int | None = None,
    max_raster_pixels: int | None = None,
    max_tiles: int | None = None,
    max_candidates: int | None = None,
    max_aoi_area_km2: float | None = None,
    max_aoi_vertices: int | None = None,
) -> EffectiveDetectorConfig:
    concrete_sensor = canonical_sensor(sensor)
    resolved, payload = load_processing_yaml(path)
    domain = "optical" if concrete_sensor == Sensor.SENTINEL2 else "sar"
    detector_root = payload.get("ship_detection") or {}
    detector = detector_root.get(domain) if isinstance(detector_root, dict) else None
    if not isinstance(detector, dict):
        raise ValueError(f"ship_detection.{domain} is missing in {resolved}")

    preprocessing_root = payload.get("preprocessing") or {}
    preprocessing = (
        preprocessing_root.get(concrete_sensor.value, {})
        if isinstance(preprocessing_root, dict)
        else {}
    )
    if not isinstance(preprocessing, dict):
        raise ValueError(f"preprocessing.{concrete_sensor.value} must be a mapping")

    limits_root = payload.get("resource_limits") or {}
    if not isinstance(limits_root, dict):
        raise ValueError("resource_limits must be a mapping")

    method = str(detector.get("method", "local_cfar")).strip().lower()
    values: dict[str, int | float] = {
        "threshold_sigma": _number(detector, "threshold_sigma", 3.5, float),
        "min_area_px": _number(detector, "min_area_px", 2, int),
        "max_area_px": _number(detector, "max_area_px", 5000, int),
        "local_window_px": _number(detector, "local_window_px", 31, int),
        "guard_window_px": _number(detector, "guard_window_px", 5, int),
        "min_contrast_sigma": _number(detector, "min_contrast_sigma", 0.0, float),
        "min_training_fraction": _number(
            detector,
            "min_training_fraction",
            0.5,
            float,
        ),
        "tile_size_px": _number(preprocessing, "tile_size_px", 1024, int),
        "tile_overlap_px": _number(preprocessing, "tile_overlap_px", 128, int),
        "normalization_sample_pixels": _number(
            preprocessing,
            "normalization_sample_pixels",
            1_000_000,
            int,
        ),
        "max_aoi_area_km2": _number(
            limits_root,
            "max_aoi_area_km2",
            25_000.0,
            float,
        ),
        "max_aoi_vertices": _number(
            limits_root,
            "max_aoi_vertices",
            5_000,
            int,
        ),
        "max_raster_pixels": _number(
            limits_root,
            "max_raster_pixels",
            2_000_000_000,
            int,
        ),
        "max_tiles": _number(limits_root, "max_tiles", 20_000, int),
        "max_candidates": _number(limits_root, "max_candidates", 10_000, int),
    }

    env_spec: dict[str, tuple[str, type[int] | type[float]]] = {
        "threshold_sigma": ("MARINE_TRACK_DETECTION_THRESHOLD_SIGMA", float),
        "min_area_px": ("MARINE_TRACK_DETECTION_MIN_AREA_PX", int),
        "max_area_px": ("MARINE_TRACK_DETECTION_MAX_AREA_PX", int),
        "local_window_px": ("MARINE_TRACK_DETECTION_LOCAL_WINDOW_PX", int),
        "guard_window_px": ("MARINE_TRACK_DETECTION_GUARD_WINDOW_PX", int),
        "min_contrast_sigma": ("MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA", float),
        "min_training_fraction": (
            "MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION",
            float,
        ),
        "tile_size_px": ("MARINE_TRACK_DETECTION_TILE_SIZE_PX", int),
        "tile_overlap_px": ("MARINE_TRACK_DETECTION_TILE_OVERLAP_PX", int),
        "normalization_sample_pixels": (
            "MARINE_TRACK_NORMALIZATION_SAMPLE_PIXELS",
            int,
        ),
        "max_aoi_area_km2": ("MARINE_TRACK_MAX_AOI_AREA_KM2", float),
        "max_aoi_vertices": ("MARINE_TRACK_MAX_AOI_VERTICES", int),
        "max_raster_pixels": ("MARINE_TRACK_MAX_RASTER_PIXELS", int),
        "max_tiles": ("MARINE_TRACK_MAX_TILES", int),
        "max_candidates": ("MARINE_TRACK_MAX_CANDIDATES", int),
    }
    for key, (env_name, caster) in env_spec.items():
        raw = os.getenv(env_name)
        if raw is not None and raw.strip() != "":
            try:
                values[key] = caster(raw)
            except ValueError as exc:
                raise ValueError(f"{env_name} has invalid value: {raw!r}") from exc

    explicit = {
        "threshold_sigma": threshold_sigma,
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "local_window_px": local_window_px,
        "guard_window_px": guard_window_px,
        "min_contrast_sigma": min_contrast_sigma,
        "min_training_fraction": min_training_fraction,
        "tile_size_px": tile_size_px,
        "tile_overlap_px": tile_overlap_px,
        "normalization_sample_pixels": normalization_sample_pixels,
        "max_aoi_area_km2": max_aoi_area_km2,
        "max_aoi_vertices": max_aoi_vertices,
        "max_raster_pixels": max_raster_pixels,
        "max_tiles": max_tiles,
        "max_candidates": max_candidates,
    }
    for key, value in explicit.items():
        if value is not None:
            values[key] = value

    normalized = {
        "threshold_sigma": float(values["threshold_sigma"]),
        "min_area_px": int(values["min_area_px"]),
        "max_area_px": int(values["max_area_px"]),
        "local_window_px": int(values["local_window_px"]),
        "guard_window_px": int(values["guard_window_px"]),
        "min_contrast_sigma": float(values["min_contrast_sigma"]),
        "min_training_fraction": float(values["min_training_fraction"]),
        "tile_size_px": int(values["tile_size_px"]),
        "tile_overlap_px": int(values["tile_overlap_px"]),
        "normalization_sample_pixels": int(values["normalization_sample_pixels"]),
        "max_aoi_area_km2": float(values["max_aoi_area_km2"]),
        "max_aoi_vertices": int(values["max_aoi_vertices"]),
        "max_raster_pixels": int(values["max_raster_pixels"]),
        "max_tiles": int(values["max_tiles"]),
        "max_candidates": int(values["max_candidates"]),
    }
    _validate_detector(method, normalized)

    hash_payload = {
        "schema_version": PROCESSING_CONFIG_SCHEMA_VERSION,
        "sensor": concrete_sensor.value,
        "domain": domain,
        "method": method,
        "detector": normalized,
        "preprocessing": preprocessing,
        "resource_limits": limits_root,
    }
    config_hash = hashlib.sha256(
        json.dumps(
            hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return EffectiveDetectorConfig(
        schema_version=PROCESSING_CONFIG_SCHEMA_VERSION,
        sensor=concrete_sensor.value,
        domain=domain,
        method=method,
        preprocessing=dict(preprocessing),
        source_path=str(resolved),
        config_hash=config_hash,
        **normalized,
    )


def _number(
    mapping: dict[str, Any],
    key: str,
    default: int | float,
    caster: type[int] | type[float],
) -> int | float:
    value = mapping.get(key, default)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be numeric")
    try:
        return caster(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} has invalid value: {value!r}") from exc


def _validate_detector(method: str, values: dict[str, int | float]) -> None:
    if method not in {"local_cfar", "global_threshold"}:
        raise ValueError(f"unsupported detector method: {method!r}")
    threshold_sigma = float(values["threshold_sigma"])
    min_area = int(values["min_area_px"])
    max_area = int(values["max_area_px"])
    local_window = int(values["local_window_px"])
    guard_window = int(values["guard_window_px"])
    min_contrast = float(values["min_contrast_sigma"])
    min_training_fraction = float(values["min_training_fraction"])
    tile_size = int(values["tile_size_px"])
    tile_overlap = int(values["tile_overlap_px"])
    normalization_sample_pixels = int(values["normalization_sample_pixels"])
    max_aoi_area_km2 = float(values["max_aoi_area_km2"])
    max_aoi_vertices = int(values["max_aoi_vertices"])
    max_raster_pixels = int(values["max_raster_pixels"])
    max_tiles = int(values["max_tiles"])
    max_candidates = int(values["max_candidates"])

    if threshold_sigma <= 0 or threshold_sigma > 100:
        raise ValueError("threshold_sigma must be in (0, 100]")
    if min_area < 1 or max_area < min_area:
        raise ValueError("area bounds must satisfy 1 <= min_area_px <= max_area_px")
    if local_window < 0 or (local_window > 0 and (local_window < 3 or local_window % 2 == 0)):
        raise ValueError("local_window_px must be 0 or an odd integer >= 3")
    if guard_window < 0 or (guard_window > 0 and guard_window % 2 == 0):
        raise ValueError("guard_window_px must be 0 or an odd integer")
    if local_window > 0 and guard_window >= local_window:
        raise ValueError("guard_window_px must be smaller than local_window_px")
    if min_contrast < 0 or min_contrast > 100:
        raise ValueError("min_contrast_sigma must be in [0, 100]")
    if not 0.0 < min_training_fraction <= 1.0:
        raise ValueError("min_training_fraction must be in (0, 1]")
    if tile_size < 128:
        raise ValueError("tile_size_px must be >= 128")
    if tile_overlap < 0 or tile_overlap >= tile_size:
        raise ValueError("tile_overlap_px must be in [0, tile_size_px)")
    # The ownership boundary lies near the midpoint of the overlap. Each
    # owning tile therefore needs two CFAR radii of overlap so that its
    # complete outer training window is available at the boundary.
    minimum_overlap = 2 * (local_window // 2)
    if local_window > 0 and tile_overlap < minimum_overlap:
        raise ValueError(
            "tile_overlap_px is too small for the CFAR training/guard halo; "
            f"minimum is {minimum_overlap}"
        )
    if normalization_sample_pixels < 10_000:
        raise ValueError("normalization_sample_pixels must be >= 10000")
    if max_aoi_area_km2 <= 0 or max_aoi_vertices < 4:
        raise ValueError("AOI resource limits must be positive and allow a polygon")
    if max_raster_pixels < 1 or max_tiles < 1 or max_candidates < 1:
        raise ValueError("processing resource limits must be positive")
