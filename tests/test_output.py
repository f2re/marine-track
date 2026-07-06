from datetime import datetime, timezone
import json

from marine_track.models import VesselDetection
from marine_track.output import write_geojson


def test_write_geojson(tmp_path):
    detection = VesselDetection(
        detection_id="d1",
        lon=37.0,
        lat=44.0,
        satellite="sentinel-1",
        provider="asf",
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        confidence=0.7,
    )
    path = write_geojson([detection], tmp_path / "detections.geojson")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert data["features"][0]["geometry"]["coordinates"] == [37.0, 44.0]
    assert data["features"][0]["properties"]["detection_id"] == "d1"
