from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

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
    "marine_track.cli",
    "marine_track.pipeline",
    "marine_track.telegram_bot",
)


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
    aoi = Path(os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson"))
    if not aoi.is_file():
        errors.append(f"default AOI not found: {aoi}")
    out_dir = Path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"))
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
    print("Runtime check OK: imports, bot modules, default AOI and output directory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
