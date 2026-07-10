from __future__ import annotations

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
        f'''preprocessing:
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
''',
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
