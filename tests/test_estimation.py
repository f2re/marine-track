import pytest

from marine_track.estimation import (
    LonLat,
    bearing_deg,
    haversine_distance_m,
    reciprocal_heading_deg,
    speed_from_displacement,
    speed_from_kelvin_wavelength,
)
from marine_track.validation import angular_difference_deg


def test_speed_from_displacement():
    mps, knots = speed_from_displacement(100.0, 10.0)
    assert mps == pytest.approx(10.0)
    assert knots == pytest.approx(19.4384449244)


def test_speed_from_kelvin_wavelength():
    mps, knots = speed_from_kelvin_wavelength(100.0)
    assert mps == pytest.approx(12.493, rel=1e-3)
    assert knots == pytest.approx(24.286, rel=1e-3)


def test_reciprocal_heading():
    assert reciprocal_heading_deg(0.0) == pytest.approx(180.0)
    assert reciprocal_heading_deg(270.0) == pytest.approx(90.0)


def test_bearing_and_distance():
    a = LonLat(lon=0.0, lat=0.0)
    b = LonLat(lon=0.1, lat=0.0)
    assert bearing_deg(a, b) == pytest.approx(90.0)
    assert haversine_distance_m(a, b) == pytest.approx(11119.5, rel=1e-3)


def test_angular_difference_wrap():
    assert angular_difference_deg(350, 10) == pytest.approx(20)
    assert angular_difference_deg(10, 350) == pytest.approx(20)
