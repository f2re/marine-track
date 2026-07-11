from __future__ import annotations

import numpy as np
import pytest

from marine_track.models import Sensor
from marine_track.sensor_preprocessing import (
    SensorPreprocessingError,
    build_local_preprocessing_plan,
    ensure_detection_sensor_supported,
    nodata_aware_lee_filter,
    read_preprocessed_band,
)


class FakeDataset:
    def __init__(self, values: np.ndarray, mask: np.ndarray | None = None):
        self.values = values
        self.mask = np.zeros(values.shape, dtype=bool) if mask is None else mask

    def read(self, band: int, **kwargs):
        assert band == 1
        del kwargs
        return np.ma.array(self.values, mask=self.mask)


def test_amplitude_plan_is_relative_and_not_called_calibrated():
    plan = build_local_preprocessing_plan(
        Sensor.SENTINEL1,
        {"speckle_filter": "none"},
        asset_key="vv",
        input_units="amplitude",
        polarization="VV",
    )

    assert plan.input_domain == "amplitude"
    assert plan.transform == "amplitude_to_relative_db"
    assert plan.output_domain == "relative_backscatter_db"
    assert plan.calibration_status == "relative_uncalibrated_amplitude"
    assert "sentinel1_calibration_and_noise_luts_not_applied" in plan.warnings


def test_provider_declared_sigma0_is_preserved_as_calibrated_backscatter():
    plan = build_local_preprocessing_plan(
        Sensor.SENTINEL1,
        {"speckle_filter": "none"},
        asset_key="sigma0_vv",
        input_units="sigma0",
        collection="sentinel-1-rtc",
        polarization="VV",
    )

    assert plan.transform == "power_to_db"
    assert plan.output_domain == "provider_declared_backscatter_db"
    assert plan.calibration_status == "provider_declared_calibrated_backscatter"
    assert plan.warnings == ()


def test_lee_filter_runs_in_native_amplitude_domain_before_db(monkeypatch):
    import marine_track.sensor_preprocessing as preprocessing

    seen: list[np.ndarray] = []

    def capture(image: np.ndarray, window_px: int) -> np.ndarray:
        assert window_px == 5
        seen.append(image.copy())
        return image

    monkeypatch.setattr(preprocessing, "nodata_aware_lee_filter", capture)
    values = np.array([[0.0, 1.0], [10.0, 100.0]], dtype="float32")
    plan = build_local_preprocessing_plan(
        Sensor.SENTINEL1,
        {"speckle_filter": "lee", "lee_window_px": 5},
        input_units="amplitude",
    )

    output = read_preprocessed_band(FakeDataset(values), plan)

    assert len(seen) == 1
    np.testing.assert_array_equal(seen[0], values)
    assert output[1, 1] == pytest.approx(40.0)


def test_lee_filter_preserves_nodata_and_nonfinite_pixels():
    image = np.ones((9, 9), dtype="float32")
    image[4, 4] = np.nan
    image[2, 2] = 8.0

    filtered = nodata_aware_lee_filter(image, 5)

    assert np.isnan(filtered[4, 4])
    assert np.isfinite(filtered[2, 2])
    assert np.isfinite(filtered[np.isfinite(image)]).all()


def test_sentinel2_single_band_fails_closed_without_explicit_override(monkeypatch):
    monkeypatch.delenv(
        "MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL",
        raising=False,
    )
    with pytest.raises(SensorPreprocessingError, match="operational detection is disabled"):
        ensure_detection_sensor_supported(Sensor.SENTINEL2)

    monkeypatch.setenv("MARINE_TRACK_ENABLE_SENTINEL2_SINGLE_BAND_EXPERIMENTAL", "1")
    ensure_detection_sensor_supported(Sensor.SENTINEL2)
