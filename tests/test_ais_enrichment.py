from datetime import datetime, timezone

from marine_track.detection_pipeline import enrich_detections_with_ais
from marine_track.models import HeadingMethod, SpeedMethod, VesselDetection


def test_ais_enrichment_matches_detection_and_extracts_track(tmp_path):
    csv_path = tmp_path / "ais.csv"
    csv_path.write_text(
        "mmsi,time,lon,lat,sog_knots,cog_deg\n"
        "123456789,2026-07-07T11:50:00Z,36.99,44.99,11.0,80\n"
        "123456789,2026-07-07T12:10:00Z,37.01,45.01,13.0,82\n",
        encoding="utf-8",
    )
    detection = VesselDetection(
        detection_id="d1",
        lon=37.0,
        lat=45.0,
        satellite="sentinel1",
        provider="planetary_computer",
        product_id="scene",
        acquisition_time=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        confidence=0.9,
    )

    enrich_detections_with_ais(
        [detection],
        ais_csv=csv_path,
        match_window_min=30,
        track_window_min=30,
        max_distance_m=5000,
    )

    assert detection.validation_status == "ais_reference_matched"
    assert detection.validation["ais_reference"]["not_ground_truth"] is True
    reference = detection.references.ais
    assert reference is not None
    assert reference.mmsi == "123456789"
    assert reference.sog_knots == 12.0
    assert reference.cog_deg == 81.0
    assert len(reference.track) == 2
    assert reference.not_ground_truth is True
    assert detection.speed_method == SpeedMethod.NOT_ESTIMATED
    assert detection.speed_reference is None
    assert detection.speed_knots is None
    assert detection.heading_method == HeadingMethod.NOT_ESTIMATED
    assert detection.heading_deg is None


def test_ais_enrichment_missing_csv_is_warning(tmp_path):
    detection = VesselDetection(
        detection_id="d1",
        lon=37.0,
        lat=45.0,
        satellite="sentinel1",
        provider="planetary_computer",
        product_id="scene",
        acquisition_time=datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        confidence=0.9,
    )

    enrich_detections_with_ais([detection], ais_csv=tmp_path / "missing.csv")

    assert detection.validation_status == "unvalidated"
    assert "AIS CSV not found" in detection.metadata["ais_reference_warning"]
