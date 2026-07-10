from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"
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
    "marine_track.calibration",
    "marine_track.calibration_phase2",
    "marine_track.calibration_phase2_tiles",
    "marine_track.calibration_phase2_evaluation",
    "marine_track.telegram_bot",
    "marine_track.telegram_calibration",
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


def load_dotenv(path: Path = ENV_FILE) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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
    aoi = project_path(os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson"))
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


def check_telegram_env() -> list[str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token:
        return []
    return ["TELEGRAM_BOT_TOKEN is empty; set it in /opt/marine_track/.env before deploy"]


def check_numeric_env() -> list[str]:
    errors: list[str] = []
    float_names = {
        "MARINE_TRACK_AIS_MAX_DISTANCE_M",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION",
        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT",
    }
    names = (
        "MARINE_TRACK_DEFAULT_LOOKBACK_HOURS",
        "MARINE_TRACK_MAX_RESULTS",
        "MARINE_TRACK_MAX_CONCURRENT_JOBS",
        "MARINE_TRACK_DETECTION_MAX_CROPS",
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
    )
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        try:
            float(raw) if name in float_names else int(raw)
        except ValueError:
            errors.append(f"{name} must be numeric, got {raw!r}")
    return errors


def main() -> int:
    load_dotenv()
    errors = check_imports() + check_paths() + check_telegram_env() + check_numeric_env()
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
