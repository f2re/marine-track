from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

REQUIRED_MODULES = (
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
    "pystac_client",
    "asf_search",
    "planetary_computer",
    "sentinelhub",
    "copernicusmarine",
    "marine_track.cli",
    "marine_track.pipeline",
    "marine_track.telegram_bot",
    "marine_track.telegram_detection",
    "marine_track.detection_pipeline",
    "marine_track.detection_scene_search",
    "marine_track.scene_materializer",
    "marine_track.land_mask",
    "marine_track.provider_auth",
    "marine_track.data_sources.sentinelhub_provider",
    "marine_track.copernicus_marine_provider",
    "marine_track.ais_sources",
    "marine_track.noaa_ais_source",
)


def project_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_DIR / path


def check_imports() -> list[str]:
    errors: list[str] = []
    for module_name in REQUIRED_MODULES:
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
    local_track_csv = os.getenv("MARINE_TRACK_AIS_CSV", "").strip()
    if local_track_csv and not project_path(local_track_csv).is_file():
        errors.append(f"local vessel track CSV not found: {project_path(local_track_csv)}")
    out_dir = project_path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"))
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".runtime_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"output dir is not writable: {out_dir}: {exc}")
    return errors


def check_numeric_env() -> list[str]:
    errors: list[str] = []
    for name in (
        "MARINE_TRACK_DEFAULT_LOOKBACK_HOURS",
        "MARINE_TRACK_MAX_RESULTS",
        "MARINE_TRACK_MAX_CONCURRENT_JOBS",
        "MARINE_TRACK_DETECTION_MAX_CROPS",
        "MARINE_TRACK_SHORELINE_BUFFER_M",
    ):
        raw = os.getenv(name)
        if raw is None:
            continue
        try:
            int(raw)
        except ValueError:
            errors.append(f"{name} must be integer, got {raw!r}")
    return errors


def main() -> int:
    errors = check_imports() + check_paths() + check_numeric_env()
    if errors:
        print("Runtime check failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Runtime check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
