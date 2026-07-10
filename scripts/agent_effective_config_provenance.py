from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact match, got {count}: {old[:100]!r}")
    write(path, content.replace(old, new, 1))


def regex_once(path: str, pattern: str, replacement: str) -> None:
    content = read(path)
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, got {count}: {pattern!r}")
    write(path, updated)


replace_once(
    "src/marine_track/detection_pipeline.py",
    "from marine_track.output import write_csv, write_geojson, write_parquet\n",
    """from marine_track.output import write_csv, write_geojson, write_parquet
from marine_track.processing_config import EffectiveDetectorConfig, load_effective_detector_config
from marine_track.provenance import (
    build_reproducibility_manifest,
    safe_path_reference,
    write_redacted_json,
)
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """    max_crops: int = 10,
    threshold_sigma: float = 3.5,
    min_area_px: int = 2,
    max_area_px: int = 5000,
    local_window_px: int = 31,
    guard_window_px: int = 5,
    min_contrast_sigma: float | None = None,
""",
    """    max_crops: int = 10,
    threshold_sigma: float | None = None,
    min_area_px: int | None = None,
    max_area_px: int | None = None,
    local_window_px: int | None = None,
    guard_window_px: int | None = None,
    min_contrast_sigma: float | None = None,
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)
    min_contrast_sigma = min_contrast_sigma if min_contrast_sigma is not None else env_float(
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
        0.0,
        0.0,
        100.0,
    )

    report_progress(progress_callback, "2/5 materialize · подготовка GeoTIFF/COG")
""",
    """    run_dir = output_dir / "detections" / token
    run_dir.mkdir(parents=True, exist_ok=True)

    report_progress(progress_callback, "2/5 materialize · подготовка GeoTIFF/COG")
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """    )

    report_progress(progress_callback, "3/5 detect · CFAR, scale, shape, wake/AIS")
    detections = detect_candidates_from_raster(
""",
    """    )
    effective_config = load_effective_detector_config(
        materialized.scene.sensor,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
    )
    detector_kwargs = effective_config.detector_kwargs()

    report_progress(progress_callback, "3/5 detect · CFAR, scale, shape, wake/AIS")
    detections = detect_candidates_from_raster(
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
""",
    """        **detector_kwargs,
""",
)
replace_once(
    "src/marine_track/detection_pipeline.py",
    """        crop_pngs,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
        land_mask_geojson=land_mask_geojson,
""",
    """        crop_pngs,
        effective_config=effective_config,
        land_mask_geojson=land_mask_geojson,
""",
)
regex_once(
    "src/marine_track/detection_pipeline.py",
    r"""def write_report_json\(\n.*?\n    path.write_text\(json.dumps\(payload, ensure_ascii=False, indent=2\), encoding="utf-8"\)\n    return path\n""",
    '''def write_report_json(
    path: Path,
    token: str,
    materialized: MaterializedScene,
    detections: list[VesselDetection],
    crop_pngs: list[Path],
    effective_config: EffectiveDetectorConfig,
    land_mask_geojson: str | Path | None,
    shoreline_buffer_m: float,
) -> Path:
    output_dir = path.parents[2]
    detector = effective_config.as_report_dict()
    detector.update(
        confidence_formula=(
            "ranking score; heuristic or explicitly promoted calibration profile, not probability"
        ),
        land_mask_reference=safe_path_reference(land_mask_geojson, output_dir),
        shoreline_buffer_m=shoreline_buffer_m,
    )
    payload = {
        "schema_version": 2,
        "token": token,
        "provider": materialized.provider,
        "sensor": materialized.sensor,
        "product_id": materialized.scene.product_id,
        "acquisition_time": materialized.scene.acquisition_time.isoformat(),
        "raster_key": materialized.raster_key,
        "raster_reference": safe_path_reference(materialized.raster_path, output_dir),
        "raster_cache_hit": materialized.cache_hit,
        "aoi_crop": materialized.cropped,
        "detector": detector,
        "reproducibility": build_reproducibility_manifest(
            materialized,
            effective_config,
            output_dir=output_dir,
        ),
        "wake_speed_enrichment": {
            "enabled": True,
            "experimental": True,
            "method": "cross_axis_profile_peaks + deep_water_kelvin_wavelength",
            "note": "Research proxy only; AIS remains a separate external reference.",
        },
        "ais_enrichment": {
            "enabled": bool(os.getenv("MARINE_TRACK_AIS_CSV", "").strip()),
            "csv_reference": safe_path_reference(
                os.getenv("MARINE_TRACK_AIS_CSV", "").strip() or None,
                output_dir,
            ),
            "match_window_min": env_int("MARINE_TRACK_AIS_MATCH_WINDOW_MIN", 30, 1, 24 * 60),
            "track_window_min": env_int("MARINE_TRACK_AIS_TRACK_WINDOW_MIN", 60, 1, 24 * 60),
            "max_distance_m": env_float(
                "MARINE_TRACK_AIS_MAX_DISTANCE_M", 3000.0, 1.0, 100_000.0
            ),
        },
        "detections_count": len(detections),
        "crop_count": len(crop_pngs),
        "detections": [detection.model_dump(mode="json") for detection in detections],
        "crops": [safe_path_reference(item, output_dir) for item in crop_pngs],
    }
    return write_redacted_json(path, payload, base_dir=output_dir)
''',
)

replace_once(
    "src/marine_track/telegram_detection.py",
    """            max_crops=config.detection_max_crops,
            threshold_sigma=3.5,
            min_area_px=2,
            max_area_px=5000,
            local_window_px=31,
            guard_window_px=5,
            land_mask_geojson=config.land_mask_geojson,
""",
    """            max_crops=config.detection_max_crops,
            land_mask_geojson=config.land_mask_geojson,
""",
)

replace_once(
    "src/marine_track/cli.py",
    "from marine_track.pipeline import parse_utc_datetime, run_search_stage, search_scenes_with_fallback\n",
    """from marine_track.pipeline import parse_utc_datetime, run_search_stage, search_scenes_with_fallback
from marine_track.processing_config import load_effective_detector_config
""",
)
regex_once(
    "src/marine_track/cli.py",
    r"""@app.command\("detect-raster"\)\ndef detect_raster\(\n.*?\n    console.print\(f"\[green\]Saved \{len\(detections\)\} detections to \{output\}\[/green\]"\)\n""",
    '''@app.command("detect-raster")
def detect_raster(
    raster: Path = typer.Option(..., exists=True, readable=True, help="Single-band GeoTIFF path"),
    output: Path = typer.Option(Path("runs/latest/detections.geojson")),
    satellite: Sensor = typer.Option(Sensor.SENTINEL1),
    provider: str = typer.Option("local"),
    product_id: str = typer.Option("local-raster"),
    acquisition_time: str = typer.Option(..., help="UTC acquisition time"),
    threshold_sigma: float | None = typer.Option(None),
    min_area_px: int | None = typer.Option(None),
    max_area_px: int | None = typer.Option(None),
    local_window_px: int | None = typer.Option(None),
    guard_window_px: int | None = typer.Option(None),
    min_contrast_sigma: float | None = typer.Option(None),
) -> None:
    """Detect bright candidates using the same effective config as Telegram."""
    effective = load_effective_detector_config(
        satellite,
        threshold_sigma=threshold_sigma,
        min_area_px=min_area_px,
        max_area_px=max_area_px,
        local_window_px=local_window_px,
        guard_window_px=guard_window_px,
        min_contrast_sigma=min_contrast_sigma,
    )
    detections = detect_candidates_from_raster(
        path=raster,
        satellite=satellite.value,
        provider=provider,
        product_id=product_id,
        acquisition_time=parse_utc_datetime(acquisition_time),
        **effective.detector_kwargs(),
    )
    write_geojson(detections, output)
    write_csv(detections, output.with_suffix(".csv"))
    write_parquet(detections, output.with_suffix(".parquet"))
    console.print(
        f"[green]Saved {len(detections)} candidates to {output}[/green] "
        f"config={effective.config_hash[:12]}"
    )


@app.command("effective-config")
def effective_config_command(
    sensor: Sensor = typer.Option(Sensor.SENTINEL1),
) -> None:
    """Print validated detector parameters and reproducibility hash."""
    effective = load_effective_detector_config(sensor)
    console.print_json(data=effective.as_report_dict())
''',
)

replace_once(
    "runtime_check.py",
    "    \"marine_track.pipeline\",\n",
    """    "marine_track.pipeline",
    "marine_track.processing_config",
    "marine_track.provenance",
""",
)
replace_once(
    "runtime_check.py",
    """def check_paths() -> list[str]:
    errors: list[str] = []
""",
    """def check_paths() -> list[str]:
    errors: list[str] = []
    processing_config = project_path(
        os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml")
    )
    if not processing_config.is_file():
        errors.append(f"processing config not found: {processing_config}")
""",
)
replace_once(
    "runtime_check.py",
    """def check_numeric_env() -> list[str]:
""",
    """def check_processing_config() -> list[str]:
    try:
        from marine_track.models import Sensor
        from marine_track.processing_config import load_effective_detector_config

        path = project_path(os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml"))
        load_effective_detector_config(Sensor.SENTINEL1, path=path)
        load_effective_detector_config(Sensor.SENTINEL2, path=path)
        return []
    except Exception as exc:
        return [f"processing config invalid: {exc}"]


def check_numeric_env() -> list[str]:
""",
)
replace_once(
    "runtime_check.py",
    """        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT",
    }
""",
    """        "MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT",
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA",
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
    }
""",
)
replace_once(
    "runtime_check.py",
    """        "MARINE_TRACK_DETECTION_MAX_CROPS",
""",
    """        "MARINE_TRACK_DETECTION_MAX_CROPS",
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA",
        "MARINE_TRACK_DETECTION_MIN_AREA_PX",
        "MARINE_TRACK_DETECTION_MAX_AREA_PX",
        "MARINE_TRACK_DETECTION_LOCAL_WINDOW_PX",
        "MARINE_TRACK_DETECTION_GUARD_WINDOW_PX",
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA",
""",
)
replace_once(
    "runtime_check.py",
    "    errors = check_imports() + check_paths() + check_telegram_env() + check_numeric_env()\n",
    """    errors = (
        check_imports()
        + check_paths()
        + check_telegram_env()
        + check_processing_config()
        + check_numeric_env()
    )
""",
)

replace_once(
    "config/processing.yaml",
    """    threshold_sigma: 3.5
    land_mask_mode: optional_geojson
""",
    """    threshold_sigma: 3.5
    min_contrast_sigma: 0.0
    land_mask_mode: optional_geojson
""",
)
replace_once(
    "config/processing.yaml",
    """    threshold_sigma: 3.5
    contrast_percentile: 98.5
""",
    """    threshold_sigma: 3.5
    min_contrast_sigma: 0.0
    contrast_percentile: 98.5
""",
)

replace_once(
    ".env.example",
    """# Detection defaults
MARINE_TRACK_DETECTION_MAX_CROPS=10
MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA=0
""",
    """# Detection effective config. YAML is the baseline; non-empty env values override it.
MARINE_TRACK_PROCESSING_CONFIG=config/processing.yaml
MARINE_TRACK_DETECTION_MAX_CROPS=10
MARINE_TRACK_DETECTION_THRESHOLD_SIGMA=
MARINE_TRACK_DETECTION_MIN_AREA_PX=
MARINE_TRACK_DETECTION_MAX_AREA_PX=
MARINE_TRACK_DETECTION_LOCAL_WINDOW_PX=
MARINE_TRACK_DETECTION_GUARD_WINDOW_PX=
MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA=
# Optional immutable release identifier when the install tree has no .git metadata.
MARINE_TRACK_CODE_VERSION=
""",
)

write(
    "docs/EFFECTIVE_CONFIG_PROVENANCE.md",
    """# Effective processing configuration and reproducibility

`config/processing.yaml` is now the shared baseline for CLI and Telegram detection. Optional
`MARINE_TRACK_DETECTION_*` values override YAML; explicit CLI/function arguments override both.
The resolved values are validated and hashed before detection.

Every `report.json` contains schema v2, the exact effective detector parameters, config hash,
code/package/Python version, sensor/product/asset identity, redacted asset URL, auth mode,
raster dimensions/CRS/transform/pixel size and AOI hash. Absolute paths and URL query credentials
are removed recursively before atomic JSON write.

Use `marine-track effective-config --sensor sentinel1` to inspect the active values. Deployment
preflight rejects missing or invalid processing config. Set `MARINE_TRACK_CODE_VERSION` to an
immutable release SHA when `.git` is absent from the production release directory.
""",
)

write(
    "tests/test_processing_config_provenance.py",
    """from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from marine_track.detection_pipeline import run_detection_for_token
from marine_track.models import Scene, Sensor
from marine_track.processing_config import load_effective_detector_config
from marine_track.provenance import redact_value, sanitize_url
from marine_track.telegram_scene_browser import register_scenes


def write_config(path, *, threshold=2.25, local_window=31, guard_window=5):
    path.write_text(
        f"""preprocessing:
  sentinel1:
    preferred_product: RTC
  sentinel2:
    target_resolution_m: 10
ship_detection:
  sar:
    method: local_cfar
    min_area_px: 3
    max_area_px: 400
    local_window_px: {local_window}
    guard_window_px: {guard_window}
    threshold_sigma: {threshold}
    min_contrast_sigma: 0.5
  optical:
    method: local_cfar
    min_area_px: 2
    max_area_px: 300
    local_window_px: 31
    guard_window_px: 5
    threshold_sigma: 3.0
    min_contrast_sigma: 0.0
""",
        encoding="utf-8",
    )


def write_raster(path):
    image = np.zeros((64, 64), dtype="float32")
    image[20:23, 30:33] = 100.0
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=64,
        width=64,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(10.0, 20.0, 0.01, 0.01),
    ) as dataset:
        dataset.write(image, 1)
    return path


def test_yaml_env_and_explicit_override_precedence(tmp_path, monkeypatch):
    path = tmp_path / "processing.yaml"
    write_config(path)
    baseline = load_effective_detector_config(Sensor.SENTINEL1, path=path)
    assert baseline.threshold_sigma == 2.25
    assert baseline.min_area_px == 3

    monkeypatch.setenv("MARINE_TRACK_DETECTION_THRESHOLD_SIGMA", "4.5")
    env_config = load_effective_detector_config(Sensor.SENTINEL1, path=path)
    assert env_config.threshold_sigma == 4.5
    explicit = load_effective_detector_config(
        Sensor.SENTINEL1, path=path, threshold_sigma=1.75
    )
    assert explicit.threshold_sigma == 1.75
    assert explicit.config_hash != baseline.config_hash


def test_invalid_processing_windows_are_rejected(tmp_path):
    path = tmp_path / "processing.yaml"
    write_config(path, local_window=30)
    with pytest.raises(ValueError, match="odd"):
        load_effective_detector_config(Sensor.SENTINEL1, path=path)


def test_url_and_path_redaction():
    assert sanitize_url("https://user:pass@example.test/a.tif?token=secret") == (
        "https://example.test/a.tif"
    )
    redacted = redact_value(
        {
            "access_token": "secret",
            "href": "https://example.test/a.tif?sig=secret",
            "path": "/opt/private/a.tif",
        }
    )
    assert redacted["access_token"] == "[redacted]"
    assert redacted["href"] == "https://example.test/a.tif"
    assert redacted["path"] == "<local>/a.tif"


def test_detection_report_uses_effective_config_and_redacted_provenance(tmp_path, monkeypatch):
    config_path = tmp_path / "processing.yaml"
    write_config(config_path, threshold=1.0, local_window=0, guard_window=0)
    monkeypatch.setenv("MARINE_TRACK_PROCESSING_CONFIG", str(config_path))
    monkeypatch.setenv("MARINE_TRACK_CODE_VERSION", "test-commit")

    raster = write_raster(tmp_path / "scene.tif")
    scene = Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="LOCAL_PROVENANCE_TEST",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": str(raster)},
        metadata={"units": "amplitude", "collection": "local-test"},
    )
    scenes_json = tmp_path / "scenes.json"
    scenes_json.write_text("[]", encoding="utf-8")
    token = register_scenes(
        tmp_path,
        "local",
        Sensor.SENTINEL1,
        [scene],
        scenes_json,
        None,
        owner_user_id=100,
        owner_chat_id=200,
    )[0]
    result = run_detection_for_token(
        token,
        tmp_path,
        owner_user_id=100,
        owner_chat_id=200,
    )
    report_text = result.report_json.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert report["schema_version"] == 2
    assert report["detector"]["threshold_sigma"] == 1.0
    assert report["reproducibility"]["code"]["commit"] == "test-commit"
    assert report["reproducibility"]["scene"]["asset"]["units"] == "amplitude"
    assert report["reproducibility"]["raster"]["width"] == 64
    assert str(tmp_path) not in report_text
    assert "config_hash" in report["detector"]
""",
)

print("effective config and provenance migration applied")
