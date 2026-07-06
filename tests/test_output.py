import json
from datetime import datetime, timezone

import pandas as pd

from marine_track.models import VesselDetection
from marine_track.output import write_geojson, write_parquet


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


def test_write_parquet_serializes_nested_fields(tmp_path):
    detection = VesselDetection(
        detection_id="d1",
        lon=37.0,
        lat=44.0,
        satellite="sentinel-1",
        provider="asf",
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        confidence=0.7,
        metadata={"wake": {"score": 12.0}},
    )
    path = write_parquet([detection], tmp_path / "detections.parquet")
    frame = pd.read_parquet(path)
    assert json.loads(frame.loc[0, "metadata"])["wake"]["score"] == 12.0
    assert json.loads(frame.loc[0, "validation"]) == {}
