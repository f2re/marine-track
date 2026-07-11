from __future__ import annotations

import importlib
import math
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
PROJECT_ENV_FILE = PROJECT_DIR / ".env"
CANONICAL_ENV_FILE = Path("/etc/marine-track/marine-track.env")
VALID_PROVIDER_PROFILES = {"all", "scene", "aux", "core"}

CORE_MODULES = (
    "numpy",
    "pandas",
    "pydantic",
    "yaml",
    "telegram",
    "typer",
    "rich",
    "shapely",
    "pyproj",
    "geopandas",
    "rasterio",
    "xarray",
    "scipy",
    "skimage",
    "cv2",
    "marine_track.cli",
    "marine_track.pipeline",
    "marine_track.processing_config",
    "marine_track.resource_limits",
    "marine_track.sensor_preprocessing",
    "marine_track.provenance",
    "marine_track.calibration",
    "marine_track.calibration_areas",
    "marine_track.calibration_area_pipeline",
    "marine_track.calibration_phase2",
    "marine_track.calibration_phase2_tiles",
    "marine_track.calibration_phase2_evaluation",
    "marine_track.telegram_bot",
    "marine_track.health",
    "marine_track.telegram_calibration",
    "marine_track.telegram_calibration_areas",
    "marine_track.telegram_calibration_phase2",
    "marine_track.telegram_detection",
    "marine_track.telegram_ui",
    "marine_track.telegram_user_state",
    "marine_track.smoke_check",
    "marine_track.provider_preflight",
    "marine_track.detection_pipeline",
    "marine_track.detection_scene_search",
    "marine_track.scene_materializer",
    "marine_track.land_mask",
    "marine_track.land_mask_update",
    "marine_track.provider_auth",
    "marine_track.ais",
    "marine_track.ais_sources",
    "marine_track.noaa_ais_source",
)

SCENE_PROVIDER_MODULES = (
    "pystac_client",
    "asf_search",
    "planetary_computer",
    "sentinelhub",
    "marine_track.data_sources.sentinelhub_provider",
)

AUX_PROVIDER_MODULES = (
    "copernicusmarine",
    "marine_track.copernicus_marine_provider",
)


def environment_file_path() -> Path:
    explicit = os.getenv("MARINE_TRACK_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit)
    if CANONICAL_ENV_FILE.is_file():
        return CANONICAL_ENV_FILE
    return PROJECT_ENV_FILE


def load_dotenv(path: Path | None = None) -> None:
    resolved = path or environment_file_path()
    if not resolved.is_file():
        return
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        parsed = value.strip().strip('"').strip("'")
        if key not in os.environ or not os.environ[key].strip():
            os.environ[key] = parsed


def provider_profile() -> str:
    value = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
    if value not in VALID_PROVIDER_PROFILES:
        raise ValueError(
            f"invalid MARINE_TRACK_PROVIDER_PROFILE={value!r}; use one of {sorted(VALID_PROVIDER_PROFILES)}"
        )
    return value


def required_modules() -> tuple[str, ...]:
    profile = provider_profile()
    modules = list(CORE_MODULES)
    if profile in {"all", "scene"}:
        modules.extend(SCENE_PROVIDER_MODULES)
    if profile in {"all", "aux"}:
        modules.extend(AUX_PROVIDER_MODULES)
    return tuple(modules)


def project_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_DIR / path


def check_imports() -> list[str]:
    errors: list[str] = []
    try:
        modules = required_modules()
    except Exception as exc:
        return [str(exc)]
    for module_name in modules:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    return errors


def check_paths() -> list[str]:
    errors: list[str] = []
    processing_config = project_path(
        os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml")
    )
    if not processing_config.is_file():
        errors.append(f"processing config not found: {processing_config}")
    aoi = project_path(
        os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson")
    )
    if not aoi.is_file():
        errors.append(f"default AOI not found: {aoi}")
    land_mask = os.getenv("MARINE_TRACK_LAND_MASK_GEOJSON", "").strip()
    if land_mask and not project_path(land_mask).is_file():
        errors.append(f"land mask GeoJSON not found: {project_path(land_mask)}")
    calibration_context = os.getenv("MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON", "").strip()
    if calibration_context and not project_path(calibration_context).is_file():
        errors.append(
            f"calibration context GeoJSON not found: {project_path(calibration_context)}"
        )
    local_track_csv = os.getenv("MARINE_TRACK_AIS_CSV", "").strip()
    if local_track_csv and not project_path(local_track_csv).is_file():
        errors.append(f"local vessel track CSV not found: {project_path(local_track_csv)}")
    for name, default in (
        ("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"),
        ("MARINE_TRACK_CACHE_DIR", "runs/cache"),
    ):
        directory = project_path(os.getenv(name, default))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            probe = directory / ".runtime_write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            errors.append(f"{name.lower()} is not writable: {directory}: {exc}")
    return errors


def env_flag(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def check_telegram_env(env_file: Path | None = None) -> list[str]:
    errors: list[str] = []
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        resolved = env_file or environment_file_path()
        errors.append(f"TELEGRAM_BOT_TOKEN is empty; set it in {resolved} before deploy")

    raw_admin_ids = os.getenv("TELEGRAM_ADMIN_IDS", "")
    parsed_ids: set[int] = set()
    for part in raw_admin_ids.replace(";", ",").replace(" ", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            parsed_ids.add(int(value))
        except ValueError:
            errors.append(f"TELEGRAM_ADMIN_IDS contains a non-integer value: {value!r}")

    public_access = env_flag("MARINE_TRACK_ALLOW_PUBLIC_BOT")
    if public_access is None:
        errors.append("MARINE_TRACK_ALLOW_PUBLIC_BOT must be boolean")
    elif not parsed_ids and not public_access:
        errors.append(
            "Telegram access is fail-closed: set TELEGRAM_ADMIN_IDS or explicitly "
            "set MARINE_TRACK_ALLOW_PUBLIC_BOT=1"
        )
    return errors


def check_processing_config() -> list[str]:
    try:
        from marine_track.models import Sensor
        from marine_track.processing_config import load_effective_detector_config

        path = project_path(
            os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml")
        )
        load_effective_detector_config(Sensor.SENTINEL1, path=path)
        load_effective_detector_config(Sensor.SENTINEL2, path=path)
        return []
    except Exception as exc:
        return [f"processing config invalid: {exc}"]


def check_feature_flags() -> list[str]:
    errors: list[str] = []
    for name in (
        "MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL",
        "MARINE_TRACK_ENABLE_WAKE_RESEARCH",
    ):
        if env_flag(name) is None:
            errors.append(f"{name} must be boolean")
    speckle_filter = os.getenv("MARINE_TRACK_S1_SPECKLE_FILTER", "lee").strip().lower()
    if speckle_filter not in {"none", "off", "false", "disabled", "lee"}:
        errors.append("MARINE_TRACK_S1_SPECKLE_FILTER must be none or lee")
    raw_window = os.getenv("MARINE_TRACK_S1_LEE_WINDOW_PX", "5").strip()
    try:
        lee_window = int(raw_window)
    except ValueError:
        errors.append(f"MARINE_TRACK_S1_LEE_WINDOW_PX must be an integer, got {raw_window!r}")
    else:
        if speckle_filter == "lee" and (lee_window < 3 or lee_window % 2 == 0):
            errors.append("MARINE_TRACK_S1_LEE_WINDOW_PX must be an odd integer >= 3")

    raw_timeout = os.getenv("MARINE_TRACK_RASTER_LOCK_TIMEOUT_S", "300").strip()
    try:
        timeout = float(raw_timeout)
    except ValueError:
        pass  # check_numeric_env reports the concrete parse error.
    else:
        if not math.isfinite(timeout) or timeout <= 0:
            errors.append("MARINE_TRACK_RASTER_LOCK_TIMEOUT_S must be finite and positive")
    return errors


def check_numeric_env() -> list[str]:
    errors: list[str] = []
    float_names = {
        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT",
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA",
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
        "MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION",
        "MARINE_TRACK_MAX_AOI_AREA_KM2",
        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
    }
    names = (
        "MARINE_TRACK_DEFAULT_LOOKBACK_HOURS",
        "MARINE_TRACK_MAX_RESULTS",
        "MARINE_TRACK_MAX_CONCURRENT_JOBS",
        "MARINE_TRACK_DETECTION_MAX_CROPS",
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA",
        "MARINE_TRACK_DETECTION_MIN_AREA_PX",
        "MARINE_TRACK_DETECTION_MAX_AREA_PX",
        "MARINE_TRACK_DETECTION_LOCAL_WINDOW_PX",
        "MARINE_TRACK_DETECTION_GUARD_WINDOW_PX",
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
        "MARINE_TRACK_CFAR_MIN_TRAINING_FRACTION",
        "MARINE_TRACK_DETECTION_TILE_SIZE_PX",
        "MARINE_TRACK_DETECTION_TILE_OVERLAP_PX",
        "MARINE_TRACK_NORMALIZATION_SAMPLE_PIXELS",
        "MARINE_TRACK_S1_LEE_WINDOW_PX",
        "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S",
        "MARINE_TRACK_MAX_AOI_AREA_KM2",
        "MARINE_TRACK_MAX_AOI_VERTICES",
        "MARINE_TRACK_MAX_RASTER_PIXELS",
        "MARINE_TRACK_MAX_TILES",
        "MARINE_TRACK_MAX_CANDIDATES",
        "MARINE_TRACK_CALIBRATION_MIN_LABELS",
        "MARINE_TRACK_CALIBRATION_MIN_POSITIVE",
        "MARINE_TRACK_CALIBRATION_MIN_NEGATIVE",
        "MARINE_TRACK_CALIBRATION_CROP_SIZE_PX",
        "MARINE_TRACK_CALIBRATION_PHASE2_MAX_TILES_PER_SCENE",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_TEST_GROUPS",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALIDATION_GROUPS",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT",
        "MARINE_TRACK_CALIBRATION_PHASE2_BOOTSTRAP_SAMPLES",
        "MARINE_TRACK_SHORELINE_BUFFER_M",
        "MARINE_TRACK_SCENE_SEARCH_TTL_MIN",
        "MARINE_TRACK_SCENE_SEARCH_CACHE_RETENTION_DAYS",
        "MARINE_TRACK_RASTER_CACHE_RETENTION_DAYS",
        "MARINE_TRACK_MASK_CACHE_RETENTION_DAYS",
        "MARINE_TRACK_DETECTION_OUTPUT_RETENTION_DAYS",
        "MARINE_TRACK_RUN_OUTPUT_RETENTION_DAYS",
        "MARINE_TRACK_AIS_MATCH_WINDOW_MIN",
        "MARINE_TRACK_AIS_TRACK_WINDOW_MIN",
        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_AIS_MAX_INTERPOLATION_GAP_MIN",
        "MARINE_TRACK_AIS_AMBIGUITY_MARGIN_M",
    )
    for name in names:
        raw = os.getenv(name)
        if raw is None or not raw.strip():
            continue
        try:
            float(raw) if name in float_names else int(raw)
        except ValueError:
            errors.append(f"{name} must be numeric, got {raw!r}")
    return errors


def main() -> int:
    env_file = environment_file_path()
    load_dotenv(env_file)
    errors = (
        check_imports()
        + check_paths()
        + check_telegram_env(env_file)
        + check_processing_config()
        + check_feature_flags()
        + check_numeric_env()
    )
    profile = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
    if errors:
        print(f"Runtime check failed (provider_profile={profile}):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"Runtime check OK (provider_profile={profile})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
