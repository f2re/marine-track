from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from marine_track.ais import assign_detections_to_ais, interpolate_track_position
from marine_track.detection_pipeline import enrich_detections_with_ais
from marine_track.models import HeadingMethod, SpeedMethod, VesselDetection


ACQUISITION = datetime(2026, 7, 10, 12, 5, tzinfo=timezone.utc)


def candidate(candidate_id: str, lon: float, lat: float, score: float = 0.7) -> VesselDetection:
    return VesselDetection(
        detection_id=candidate_id,
        lon=lon,
        lat=lat,
        satellite="sentinel1",
        provider="test",
        product_id="scene",
        acquisition_time=ACQUISITION,
        confidence=score,
    )


def ais_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "mmsi": ["111", "111", "222", "222"],
            "time": pd.to_datetime(
                [
                    "2026-07-10T12:00:00Z",
                    "2026-07-10T12:10:00Z",
                    "2026-07-10T12:00:00Z",
                    "2026-07-10T12:10:00Z",
                ],
                utc=True,
            ),
            "lon": [37.000, 37.010, 37.020, 37.030],
            "lat": [44.000, 44.000, 44.000, 44.000],
            "sog_knots": [10.0, 10.0, 12.0, 12.0],
            "cog_deg": [90.0, 90.0, 90.0, 90.0],
        }
    )


def test_legacy_confidence_input_serializes_only_ranking_score():
    detection = candidate("c1", 37.005, 44.0)

    payload = detection.model_dump(mode="json")

    assert detection.confidence == pytest.approx(0.7)
    assert payload["ranking_score"] == pytest.approx(0.7)
    assert "confidence" not in payload
    assert "speed_knots" not in payload
    assert payload["speed"] == {
        "value_knots": None,
        "method": SpeedMethod.NOT_ESTIMATED.value,
        "status": "not_estimated",
        "uncertainty_knots": None,
        "source": None,
    }


def test_interpolation_gap_gate_rejects_stale_track():
    frame = ais_frame().query("mmsi == '111'")

    point = interpolate_track_position(frame, ACQUISITION, max_gap=timedelta(minutes=5))

    assert point is None


def test_one_to_one_assignment_does_not_reuse_mmsi():
    detections = [
        candidate("c1", 37.005, 44.0),
        candidate("c2", 37.024, 44.0),
    ]

    assignments = assign_detections_to_ais(
        detections,
        ais_frame(),
        max_interpolation_gap=timedelta(minutes=20),
    )

    assert set(assignments) == {"c1", "c2"}
    assert len({str(item["mmsi"]) for item in assignments.values()}) == 2
    assert all(item["assignment_method"] == "greedy_one_to_one_distance" for item in assignments.values())
    assert all(item["not_ground_truth"] is True for item in assignments.values())


def test_pipeline_keeps_ais_as_reference_and_does_not_override_estimates(tmp_path):
    path = tmp_path / "ais.csv"
    ais_frame().to_csv(path, index=False)
    detection = candidate("c1", 37.005, 44.0)
    assert detection.heading_method == HeadingMethod.NOT_ESTIMATED

    enrich_detections_with_ais(
        [detection],
        ais_csv=path,
        max_interpolation_gap_min=20,
    )

    reference = detection.references.ais
    assert reference is not None
    assert reference.mmsi == "111"
    assert reference.sog_knots == pytest.approx(10.0)
    assert reference.cog_deg == pytest.approx(90.0)
    assert reference.not_ground_truth is True
    assert detection.speed.value_knots is None
    assert detection.speed.method == SpeedMethod.NOT_ESTIMATED
    assert detection.heading_deg is None
    assert detection.heading_method == HeadingMethod.NOT_ESTIMATED
    assert detection.validation_status.startswith("ais_reference_")
