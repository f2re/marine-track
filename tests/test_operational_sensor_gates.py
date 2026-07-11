from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.models import Sensor
from marine_track.sensor_preprocessing import SensorPreprocessingError
from marine_track.telegram_calibration_areas import area_sensor_markup


def test_sentinel2_search_rejected_before_provider_creation(tmp_path, monkeypatch):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(
        '{"type":"Polygon","coordinates":[[[30,43],[30.1,43],[30.1,43.1],[30,43.1],[30,43]]]}',
        encoding="utf-8",
    )
    monkeypatch.delenv("MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL", raising=False)
    provider_called = False

    def forbidden_providers():
        nonlocal provider_called
        provider_called = True
        raise AssertionError("providers must not be constructed")

    monkeypatch.setattr(
        "marine_track.detection_scene_search.default_stac_providers",
        forbidden_providers,
    )
    with pytest.raises(SensorPreprocessingError, match="operational detection is disabled"):
        search_detection_capable_scenes(
            aoi,
            datetime(2026, 7, 1, tzinfo=timezone.utc),
            datetime(2026, 7, 2, tzinfo=timezone.utc),
            Sensor.SENTINEL2,
            tmp_path / "out",
        )
    assert provider_called is False


def test_calibration_ui_marks_sentinel2_as_not_ready(monkeypatch):
    monkeypatch.delenv("MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL", raising=False)
    labels = [
        button.text
        for row in area_sensor_markup("b.bs_w").inline_keyboard
        for button in row
    ]
    assert "🚫 Sentinel-2 · multiband stack не готов" in labels
    assert "📡 Sentinel-1 · operational" in labels

    monkeypatch.setenv("MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL", "1")
    labels = [
        button.text
        for row in area_sensor_markup("b.bs_w").inline_keyboard
        for button in row
    ]
    assert "🧪 Sentinel-2 single-band · research" in labels
