from datetime import datetime, timezone

import pandas as pd
import pytest

from marine_track.ais import interpolate_track_position, match_detection_to_ais
from marine_track.models import VesselDetection


def test_interpolate_track_position_midpoint():
    df = pd.DataFrame(
        {
            "mmsi": ["1", "1"],
            "time": pd.to_datetime(
                ["2026-07-01T00:00:00Z", "2026-07-01T00:10:00Z"],
                utc=True,
            ),
            "lon": [37.0, 37.1],
            "lat": [44.0, 44.0],
        }
    )
    point = interpolate_track_position(df, datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc))
    assert point is not None
    assert point.lon == pytest.approx(37.05)
    assert point.lat == pytest.approx(44.0)
    assert point.sog_knots is not None


def test_match_detection_to_ais():
    ais = pd.DataFrame(
        {
            "mmsi": ["1", "1"],
            "time": pd.to_datetime(
                ["2026-07-01T00:00:00Z", "2026-07-01T00:10:00Z"],
                utc=True,
            ),
            "lon": [37.0, 37.1],
            "lat": [44.0, 44.0],
        }
    )
    detection = VesselDetection(
        detection_id="d1",
        lon=37.05,
        lat=44.0,
        satellite="sentinel-1",
        provider="asf",
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 1, 0, 5, tzinfo=timezone.utc),
        confidence=0.7,
    )
    match = match_detection_to_ais(detection, ais)
    assert match is not None
    assert match["mmsi"] == "1"
    assert match["distance_m"] == pytest.approx(0.0)
