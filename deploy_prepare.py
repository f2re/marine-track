from __future__ import annotations

import argparse
import os
from pathlib import Path

from marine_track.cache_policy import cleanup_runtime
from marine_track.land_mask_update import DEFAULT_LAND_MASK_SOURCE_URL, update_land_mask

PROJECT_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        clean_key = key.strip()
        clean_value = value.strip().strip('"').strip("'")
        values[clean_key] = clean_value
        os.environ.setdefault(clean_key, clean_value)
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def project_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_DIR / path


def truthy(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def prepare_land_mask(env_file: Path) -> None:
    if not truthy(os.getenv("MARINE_TRACK_AUTO_UPDATE_LAND_MASK"), default=True):
        print("Land mask deploy preparation: skipped by MARINE_TRACK_AUTO_UPDATE_LAND_MASK")
        return
    raw_output = os.getenv("MARINE_TRACK_LAND_MASK_GEOJSON", "").strip()
    output = project_path(raw_output) if raw_output else PROJECT_DIR / "data/masks/land.geojson"
    if not raw_output:
        write_env_value(env_file, "MARINE_TRACK_LAND_MASK_GEOJSON", str(output))
        os.environ["MARINE_TRACK_LAND_MASK_GEOJSON"] = str(output)
    force = truthy(os.getenv("MARINE_TRACK_FORCE_UPDATE_LAND_MASK"), default=False)
    if output.is_file() and output.stat().st_size > 0 and not force:
        print(f"Land mask deploy preparation: already exists, skip download: {output}")
        return
    source = os.getenv("MARINE_TRACK_LAND_MASK_SOURCE_URL", DEFAULT_LAND_MASK_SOURCE_URL)
    cache_dir = project_path(os.getenv("MARINE_TRACK_LAND_MASK_CACHE_DIR", "data/masks/cache"))
    aoi_raw = os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson")
    aoi = project_path(aoi_raw)
    result = update_land_mask(
        output_path=output,
        source=source,
        cache_dir=cache_dir,
        aoi_geojson=aoi if aoi.is_file() else None,
        force=force,
    )
    print(
        "Land mask deploy preparation: ready "
        f"path={result.output_path} features={result.feature_count} clipped={result.clipped}"
    )


def run_cleanup() -> None:
    if not truthy(os.getenv("MARINE_TRACK_CLEANUP_ON_DEPLOY"), default=True):
        print("Cleanup on deploy: skipped by MARINE_TRACK_CLEANUP_ON_DEPLOY")
        return
    reports = cleanup_runtime()
    for name, report in reports.items():
        print(
            f"Cleanup {name}: files={report.removed_files} dirs={report.removed_dirs} "
            f"bytes={report.removed_bytes}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare deploy-time caches and cleanup")
    parser.add_argument("--env-file", default=str(PROJECT_DIR / ".env"))
    parser.add_argument("--skip-land-mask", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")
    args = parser.parse_args()
    env_file = Path(args.env_file)
    load_dotenv(env_file)
    if not args.skip_land_mask:
        prepare_land_mask(env_file)
    if not args.skip_cleanup:
        run_cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
