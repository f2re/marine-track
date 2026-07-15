from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy import ndimage as ndi

from marine_track.models import SceneAsset, Sensor

_DB_EPSILON = 1e-6


class SensorPreprocessingError(RuntimeError):
    """Raised when a raster cannot be processed under the operational contract."""


@dataclass(frozen=True)
class SensorPreprocessingPlan:
    sensor: str
    asset_key: str
    collection: str | None
    processing_level: str | None
    band: str | None
    polarization: str | None
    input_units: str | None
    input_domain: str
    scale: float
    offset: float
    transform: str
    output_domain: str
    output_units: str
    calibration_status: str
    speckle_filter: str
    lee_window_px: int | None
    filter_domain: str | None
    research_only: bool
    warnings: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise SensorPreprocessingError(f"{name} must be boolean, got {raw!r}")


def sentinel2_single_band_enabled() -> bool:
    return _env_bool("MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL", False)


def wake_research_enabled() -> bool:
    return _env_bool("MARINE_TRACK_ENABLE_WAKE_RESEARCH", False)


def ensure_detection_sensor_supported(sensor: Sensor | str) -> None:
    concrete = _sensor(sensor)
    if concrete == Sensor.SENTINEL1:
        return
    if concrete == Sensor.SENTINEL2 and sentinel2_single_band_enabled():
        return
    if concrete == Sensor.SENTINEL2:
        raise SensorPreprocessingError(
            "Sentinel-2 single-band operational detection is disabled: the production path "
            "requires a co-registered B02/B03/B04/B08 stack plus SCL/cloud/water masks. "
            "Set MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL=1 only for an "
            "explicit research run."
        )
    raise SensorPreprocessingError(f"Unsupported detection sensor: {sensor!r}")


def build_scene_preprocessing_plan(
    materialized: Any,
    preprocessing: dict[str, Any],
) -> SensorPreprocessingPlan:
    """Resolve a plan from typed asset metadata and the materialized GeoTIFF.

    Provider metadata remains authoritative when it explicitly declares sigma0/gamma0 or dB.
    GRD amplitude without LUT application is deliberately labelled relative and uncalibrated.
    """

    scene = materialized.scene
    asset: SceneAsset = materialized.raster_asset
    metadata = scene.metadata if isinstance(scene.metadata, dict) else {}
    band_tags: dict[str, Any] = {}
    dataset_scale: float | None = None
    dataset_offset: float | None = None
    try:
        import rasterio

        with rasterio.open(materialized.raster_path) as dataset:
            band_tags = dict(dataset.tags(1))
            if dataset.scales:
                dataset_scale = _finite_or_none(dataset.scales[0])
            if dataset.offsets:
                dataset_offset = _finite_or_none(dataset.offsets[0])
    except Exception:
        # Materialization already validated TIFF readability. Metadata enrichment must not
        # make an otherwise readable local test raster unusable.
        band_tags = {}

    units = _first_text(
        asset.units,
        band_tags.get("units"),
        band_tags.get("unit"),
        metadata.get("units"),
        metadata.get("unit"),
        metadata.get("radiometric_units"),
        metadata.get("measurement_units"),
    )
    collection = _first_text(
        metadata.get("collection"),
        metadata.get("collection_id"),
        metadata.get("stac_collection"),
        asset.extra.get("collection") if isinstance(asset.extra, dict) else None,
    )
    processing_level = _first_text(
        metadata.get("processing_level"),
        metadata.get("product_type"),
        metadata.get("level"),
        asset.extra.get("processing_level") if isinstance(asset.extra, dict) else None,
    )
    scale = _finite_or_none(asset.scale)
    if scale is None:
        scale = dataset_scale if dataset_scale is not None else 1.0
    offset = _finite_or_none(asset.offset)
    if offset is None:
        offset = dataset_offset if dataset_offset is not None else 0.0

    return _build_plan(
        sensor=scene.sensor,
        preprocessing=preprocessing,
        asset_key=materialized.raster_key,
        asset=asset,
        collection=collection,
        processing_level=processing_level,
        input_units=units,
        scale=scale,
        offset=offset,
    )


def build_local_preprocessing_plan(
    sensor: Sensor | str,
    preprocessing: dict[str, Any],
    *,
    asset_key: str = "band1",
    input_units: str | None = None,
    scale: float = 1.0,
    offset: float = 0.0,
    collection: str | None = None,
    processing_level: str | None = None,
    polarization: str | None = None,
    band: str | None = None,
) -> SensorPreprocessingPlan:
    asset = SceneAsset(
        href=str(Path("local.tif")),
        units=input_units,
        scale=scale,
        offset=offset,
        polarization=polarization,
        band=band,
        storage="local",
        auth_mode="public",
    )
    return _build_plan(
        sensor=sensor,
        preprocessing=preprocessing,
        asset_key=asset_key,
        asset=asset,
        collection=collection,
        processing_level=processing_level,
        input_units=input_units,
        scale=scale,
        offset=offset,
    )


def _build_plan(
    *,
    sensor: Sensor | str,
    preprocessing: dict[str, Any],
    asset_key: str,
    asset: SceneAsset,
    collection: str | None,
    processing_level: str | None,
    input_units: str | None,
    scale: float,
    offset: float,
) -> SensorPreprocessingPlan:
    concrete = _sensor(sensor)
    ensure_detection_sensor_supported(concrete)
    if not math.isfinite(scale) or scale == 0:
        raise SensorPreprocessingError("Raster scale must be finite and non-zero")
    if not math.isfinite(offset):
        raise SensorPreprocessingError("Raster offset must be finite")

    if concrete == Sensor.SENTINEL2:
        return SensorPreprocessingPlan(
            sensor=concrete.value,
            asset_key=asset_key,
            collection=collection,
            processing_level=processing_level,
            band=asset.band or _band_from_key(asset_key),
            polarization=None,
            input_units=input_units,
            input_domain="optical_single_band",
            scale=float(scale),
            offset=float(offset),
            transform="scaled_identity",
            output_domain="experimental_single_band_reflectance_proxy",
            output_units=input_units or "unknown",
            calibration_status="research_single_band_not_operational",
            speckle_filter="none",
            lee_window_px=None,
            filter_domain=None,
            research_only=True,
            warnings=(
                "sentinel2_multiband_stack_missing",
                "cloud_scl_and_water_masks_not_applied",
            ),
        )

    filter_name = str(preprocessing.get("speckle_filter", "none") or "none").strip().lower()
    if filter_name in {"off", "false", "disabled"}:
        filter_name = "none"
    if filter_name not in {"none", "lee"}:
        raise SensorPreprocessingError("Sentinel-1 speckle filter must be none or lee")
    lee_window: int | None = None
    if filter_name == "lee":
        try:
            lee_window = int(preprocessing.get("lee_window_px", 5))
        except (TypeError, ValueError) as exc:
            raise SensorPreprocessingError("Sentinel-1 Lee window must be an integer") from exc
        if lee_window < 3 or lee_window % 2 == 0:
            raise SensorPreprocessingError("Sentinel-1 Lee window must be an odd integer >= 3")

    classification = _classify_s1_domain(
        input_units=input_units,
        asset_key=asset_key,
        collection=collection,
        roles=asset.roles,
        sidecars=asset.sidecars,
    )
    warnings = list(classification[5])
    if filter_name == "lee" and classification[1] in {"identity_db", "auto_relative_db"}:
        warnings.append("lee_filter_applied_in_db_or_inferred_domain")

    return SensorPreprocessingPlan(
        sensor=concrete.value,
        asset_key=asset_key,
        collection=collection,
        processing_level=processing_level,
        band=asset.band,
        polarization=asset.polarization or _polarization_from_key(asset_key),
        input_units=input_units,
        input_domain=classification[0],
        scale=float(scale),
        offset=float(offset),
        transform=classification[1],
        output_domain=classification[2],
        output_units="dB",
        calibration_status=classification[3],
        speckle_filter=filter_name,
        lee_window_px=lee_window,
        filter_domain=classification[4] if filter_name == "lee" else None,
        research_only=False,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _classify_s1_domain(
    *,
    input_units: str | None,
    asset_key: str,
    collection: str | None,
    roles: list[str],
    sidecars: dict[str, str],
) -> tuple[str, str, str, str, str, tuple[str, ...]]:
    units = _normalize(input_units)
    semantic = " ".join(
        [asset_key, collection or "", " ".join(roles), " ".join(sidecars.keys()), units]
    ).lower()
    calibrated_name = any(
        token in semantic
        for token in ("sigma0", "sigma_0", "gamma0", "gamma_0", "beta0", "rtc")
    )
    is_db = any(token in units for token in ("db", "decibel"))
    is_amplitude = any(token in units for token in ("amplitude", "dn", "digital number"))
    is_power = any(
        token in units
        for token in ("power", "intensity", "sigma", "gamma", "beta", "backscatter")
    )

    if is_db:
        status = (
            "provider_declared_calibrated_backscatter"
            if calibrated_name
            else "provider_declared_db_unverified"
        )
        warnings = () if calibrated_name else ("provider_db_calibration_not_verified",)
        return (
            "backscatter_db",
            "identity_db",
            "provider_declared_backscatter_db",
            status,
            "db",
            warnings,
        )
    if calibrated_name or is_power:
        status = (
            "provider_declared_calibrated_backscatter"
            if calibrated_name
            else "relative_uncalibrated_intensity"
        )
        warnings = () if calibrated_name else ("radiometric_calibration_not_verified",)
        return (
            "linear_backscatter" if calibrated_name else "intensity",
            "power_to_db",
            "provider_declared_backscatter_db"
            if calibrated_name
            else "relative_backscatter_db",
            status,
            "linear_power",
            warnings,
        )
    if is_amplitude:
        return (
            "amplitude",
            "amplitude_to_relative_db",
            "relative_backscatter_db",
            "relative_uncalibrated_amplitude",
            "linear_amplitude",
            ("sentinel1_calibration_and_noise_luts_not_applied",),
        )
    return (
        "unknown",
        "auto_relative_db",
        "relative_backscatter_db",
        "relative_unknown_radiometry",
        "inferred_native",
        ("input_radiometric_domain_unknown", "absolute_calibration_not_claimed"),
    )


def read_preprocessed_band(
    dataset: Any,
    plan: SensorPreprocessingPlan,
    *,
    window: Any | None = None,
    out_shape: tuple[int, int] | None = None,
    resampling: Any | None = None,
    apply_filter: bool = True,
    boundless: bool = False,
    fill_value: float | None = None,
) -> np.ndarray:
    kwargs: dict[str, Any] = {
        "window": window,
        "masked": True,
        "out_dtype": "float32",
    }
    if out_shape is not None:
        kwargs["out_shape"] = out_shape
    if resampling is not None:
        kwargs["resampling"] = resampling
    if boundless:
        kwargs["boundless"] = True
    if fill_value is not None:
        kwargs["fill_value"] = fill_value
    masked = dataset.read(1, **kwargs)
    mask = np.ma.getmaskarray(masked)
    values = np.asarray(masked.filled(np.nan), dtype="float32")
    mask = mask | ~np.isfinite(values)
    values = values * np.float32(plan.scale) + np.float32(plan.offset)
    values[mask] = np.nan

    if plan.sensor == Sensor.SENTINEL2.value:
        output = values.astype("float32", copy=False)
    else:
        filter_enabled = bool(
            apply_filter and plan.speckle_filter == "lee" and plan.lee_window_px
        )
        if filter_enabled and _filter_in_native_domain(values, plan.transform):
            values = nodata_aware_lee_filter(values, int(plan.lee_window_px))
            output = _to_db(values, plan.transform)
        else:
            output = _to_db(values, plan.transform)
            if filter_enabled:
                output = nodata_aware_lee_filter(output, int(plan.lee_window_px))
    output[mask] = np.nan
    return output.astype("float32", copy=False)


def _filter_in_native_domain(values: np.ndarray, transform: str) -> bool:
    if transform in {"power_to_db", "amplitude_to_relative_db"}:
        return True
    if transform != "auto_relative_db":
        return False
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return True
    return float(np.mean(finite < 0)) <= 0.01


def nodata_aware_lee_filter(image: np.ndarray, window_px: int) -> np.ndarray:
    if image.ndim != 2:
        raise ValueError("Lee filter input must be 2D")
    if window_px < 3 or window_px % 2 == 0:
        raise ValueError("Lee filter window must be an odd integer >= 3")
    finite = np.isfinite(image)
    if not finite.any():
        return np.full(image.shape, np.nan, dtype="float32")

    kernel = np.ones((window_px, window_px), dtype="float64")
    safe = np.where(finite, image, 0.0).astype("float64")
    count = ndi.convolve(finite.astype("float64"), kernel, mode="constant", cval=0.0)
    summed = ndi.convolve(safe, kernel, mode="constant", cval=0.0)
    squared = ndi.convolve(safe * safe, kernel, mode="constant", cval=0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = np.divide(summed, count, out=np.zeros_like(summed), where=count > 0)
        mean2 = np.divide(squared, count, out=np.zeros_like(squared), where=count > 0)
    variance = np.maximum(mean2 - mean * mean, 0.0)
    supported = finite & (count >= max(3.0, window_px))
    noise_values = variance[supported]
    noise_variance = float(np.median(noise_values)) if noise_values.size else 0.0
    weight = np.divide(
        np.maximum(variance - noise_variance, 0.0),
        np.maximum(variance, _DB_EPSILON),
    )
    filtered = mean + weight * (safe - mean)
    result = np.full(image.shape, np.nan, dtype="float32")
    result[finite] = filtered[finite].astype("float32")
    return result


def _to_db(values: np.ndarray, transform: str) -> np.ndarray:
    finite = np.isfinite(values)
    output = np.full(values.shape, np.nan, dtype="float32")
    if not finite.any():
        return output
    data = values[finite].astype("float64")
    if transform == "identity_db":
        converted = data
    elif transform == "power_to_db":
        converted = 10.0 * np.log10(np.maximum(np.abs(data), _DB_EPSILON))
    elif transform == "amplitude_to_relative_db":
        converted = 20.0 * np.log10(np.maximum(np.abs(data), _DB_EPSILON))
    elif transform == "auto_relative_db":
        # Negative finite values strongly suggest an already logarithmic raster. Positive-only
        # DN/intensity rasters are mapped to a relative dB domain without claiming calibration.
        negative_fraction = float(np.mean(data < 0))
        if negative_fraction > 0.01:
            converted = data
        else:
            converted = 10.0 * np.log10(np.maximum(np.abs(data), _DB_EPSILON))
    elif transform == "scaled_identity":
        converted = data
    else:
        raise SensorPreprocessingError(f"Unsupported radiometric transform: {transform}")
    output[finite] = converted.astype("float32")
    return output


def _sensor(value: Sensor | str) -> Sensor:
    if isinstance(value, Sensor):
        if value == Sensor.AUTO:
            raise SensorPreprocessingError("A concrete sensor is required for preprocessing")
        return value
    normalized = str(value).strip().lower().replace("-", "")
    aliases = {
        "sentinel1": Sensor.SENTINEL1,
        "s1": Sensor.SENTINEL1,
        "sar": Sensor.SENTINEL1,
        "sentinel2": Sensor.SENTINEL2,
        "s2": Sensor.SENTINEL2,
        "optical": Sensor.SENTINEL2,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise SensorPreprocessingError(f"Unsupported sensor: {value!r}") from exc


def _normalize(value: str | None) -> str:
    return (value or "").strip().lower().replace("σ", "sigma").replace("γ", "gamma")


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _polarization_from_key(asset_key: str) -> str | None:
    lowered = asset_key.lower()
    for value in ("vv", "vh", "hh", "hv"):
        if lowered == value or f"_{value}" in lowered or f"-{value}" in lowered:
            return value.upper()
    return None


def _band_from_key(asset_key: str) -> str | None:
    upper = asset_key.upper()
    for value in ("B02", "B03", "B04", "B08", "SCL"):
        if value in upper:
            return value
    return None
