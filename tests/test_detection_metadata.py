from datetime import datetime, timezone

from marine_track.models import VesselDetection


def test_vessel_detection_preserves_metadata_in_geojson():
    detection = VesselDetection(
        detection_id="d1",
        lon=37.0,
        lat=44.0,
        satellite="sentinel1",
        provider="test",
        product_id="p1",
        acquisition_time=datetime(2026, 7, 6, 5, 0, tzinfo=timezone.utc),
        confidence=0.8,
        metadata={"detector": "local_cfar", "area_px": 3},
    )
    feature = detection.to_geojson_feature()
    assert feature["properties"]["metadata"]["detector"] == "local_cfar"
    assert feature["properties"]["metadata"]["area_px"] == 3
