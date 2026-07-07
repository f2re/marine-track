from marine_track.models import Sensor
from marine_track.telegram_user_state import bbox_command_args, bbox_label, get_last_bbox, save_last_bbox


def test_last_bbox_roundtrip(tmp_path):
    save_last_bbox(
        output_dir=tmp_path,
        user_id=123,
        sensor=Sensor.SENTINEL1,
        west=36.5,
        south=43.8,
        east=38.5,
        north=45.0,
        hours=12,
    )

    bbox = get_last_bbox(tmp_path, 123)

    assert bbox is not None
    assert bbox.sensor == Sensor.SENTINEL1
    assert bbox_command_args(bbox) == ["sentinel1", "36.5", "43.8", "38.5", "45.0", "12"]
    assert "sentinel1" in bbox_label(bbox)
    assert "36.5" in bbox_label(bbox)


def test_last_bbox_missing_returns_none(tmp_path):
    assert get_last_bbox(tmp_path, 999) is None
