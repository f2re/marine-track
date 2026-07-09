import numpy as np

from marine_track.estimation import speed_from_kelvin_wavelength
from marine_track.wake import estimate_wake_wavelength_px


def test_wake_wavelength_estimator_finds_regular_profile_spacing():
    image = np.zeros((160, 160), dtype="float32")
    center_y = 80
    for offset in (-36, -24, -12, 12, 24, 36):
        image[center_y + offset, 30:130] = 1.0

    estimate = estimate_wake_wavelength_px(
        image,
        vessel_yx=(80.0, 80.0),
        axis_angle_deg=0.0,
        half_length_px=50,
        center_guard_px=6,
        min_peak_distance_px=6,
        min_peaks=4,
    )

    assert estimate is not None
    assert 10.0 <= estimate.wavelength_px <= 14.0
    assert estimate.peak_count >= 4
    assert 0.0 <= estimate.confidence <= 1.0


def test_kelvin_speed_from_wavelength_is_positive():
    speed_mps, speed_knots = speed_from_kelvin_wavelength(30.0)

    assert speed_mps > 0
    assert speed_knots > speed_mps
