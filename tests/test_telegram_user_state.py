import json

from marine_track.models import Sensor
from marine_track.telegram_user_state import (
    MAX_SAVED_BBOXES_PER_USER,
    bbox_command_args,
    bbox_label,
    delete_saved_bbox,
    get_last_bbox,
    get_saved_bboxes,
    save_last_bbox,
)


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


def test_state_file_corruption_returns_empty_state(tmp_path):
    (tmp_path / "telegram_user_state.json").write_text("{not-json", encoding="utf-8")

    assert get_last_bbox(tmp_path, 123) is None
    assert get_saved_bboxes(tmp_path, 123) == []


def test_saved_bboxes_store_multiple_and_sync_last_bbox(tmp_path):
    first = save_last_bbox(tmp_path, 123, Sensor.SENTINEL1, 36.5, 43.8, 38.5, 45.0, 12)
    second = save_last_bbox(tmp_path, 123, Sensor.SENTINEL2, 30.0, 40.0, 31.0, 41.0, 24)

    saved = get_saved_bboxes(tmp_path, 123)
    last = get_last_bbox(tmp_path, 123)

    assert [item.id for item in saved] == [second.id, first.id]
    assert last is not None
    assert bbox_command_args(last) == ["sentinel2", "30.0", "40.0", "31.0", "41.0", "24"]


def test_saved_bboxes_deduplicate_same_bbox_with_rounded_coordinates(tmp_path):
    first = save_last_bbox(tmp_path, 123, Sensor.SENTINEL1, 36.5000001, 43.8, 38.5, 45.0, 12)
    second = save_last_bbox(tmp_path, 123, Sensor.SENTINEL1, 36.5000002, 43.8, 38.5, 45.0, 12)

    saved = get_saved_bboxes(tmp_path, 123)

    assert first.id == second.id
    assert len(saved) == 1
    assert saved[0].use_count == 2


def test_saved_bboxes_are_limited_per_user(tmp_path):
    for index in range(MAX_SAVED_BBOXES_PER_USER + 3):
        save_last_bbox(
            tmp_path,
            123,
            Sensor.SENTINEL1,
            float(index),
            10.0,
            float(index) + 0.5,
            10.5,
            12,
        )

    saved = get_saved_bboxes(tmp_path, 123)

    assert len(saved) == MAX_SAVED_BBOXES_PER_USER
    assert saved[0].west == float(MAX_SAVED_BBOXES_PER_USER + 2)


def test_delete_saved_bbox_updates_last_bbox(tmp_path):
    first = save_last_bbox(tmp_path, 123, Sensor.SENTINEL1, 36.5, 43.8, 38.5, 45.0, 12)
    second = save_last_bbox(tmp_path, 123, Sensor.SENTINEL2, 30.0, 40.0, 31.0, 41.0, 24)

    assert delete_saved_bbox(tmp_path, 123, second.id) is True
    assert delete_saved_bbox(tmp_path, 123, "missing") is False

    saved = get_saved_bboxes(tmp_path, 123)
    last = get_last_bbox(tmp_path, 123)
    assert [item.id for item in saved] == [first.id]
    assert last is not None
    assert last.sensor == Sensor.SENTINEL1


def test_saved_bboxes_read_legacy_last_bbox(tmp_path):
    state = {
        "users": {
            "123": {
                "last_bbox": {
                    "sensor": "sentinel1",
                    "west": 36.5,
                    "south": 43.8,
                    "east": 38.5,
                    "north": 45.0,
                    "hours": 12,
                    "updated_at": "2026-01-01T00:00:00+00:00",
                }
            }
        }
    }
    (tmp_path / "telegram_user_state.json").write_text(json.dumps(state), encoding="utf-8")

    saved = get_saved_bboxes(tmp_path, 123)
    last = get_last_bbox(tmp_path, 123)

    assert len(saved) == 1
    assert saved[0].sensor == Sensor.SENTINEL1
    assert last is not None
    assert bbox_label(last) == saved[0].label
