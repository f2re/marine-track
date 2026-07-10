from datetime import datetime, timezone

from marine_track.models import Scene, Sensor
from marine_track.telegram_scene_browser import (
    find_scene,
    parse_scene_hours,
    parse_scene_sensor,
    register_scenes,
    scene_token,
    select_preview_asset,
)

OWNER_USER_ID = 100
OWNER_CHAT_ID = 200


def make_scene() -> Scene:
    return Scene(
        provider="test",
        sensor=Sensor.SENTINEL2,
        product_id="S2_TEST_SCENE",
        acquisition_time=datetime(2026, 7, 6, 5, 0, tzinfo=timezone.utc),
        assets={
            "data": "https://example.test/data.tif",
            "thumbnail": "https://example.test/thumb.jpg",
        },
        cloud_cover=12.5,
    )


def test_scene_token_is_stable_and_scoped():
    scene = make_scene()
    token = scene_token(scene, OWNER_USER_ID, OWNER_CHAT_ID)
    assert token == scene_token(scene, OWNER_USER_ID, OWNER_CHAT_ID)
    assert token != scene_token(scene, OWNER_USER_ID + 1, OWNER_CHAT_ID)
    assert token != scene_token(scene, OWNER_USER_ID, OWNER_CHAT_ID + 1)
    assert len(token) == 20


def test_select_preview_asset_prefers_thumbnail():
    key, href = select_preview_asset(make_scene())
    assert key == "thumbnail"
    assert href.endswith("thumb.jpg")


def test_registry_roundtrip(tmp_path):
    scene = make_scene()
    tokens = register_scenes(
        output_dir=tmp_path,
        provider="test",
        sensor=Sensor.SENTINEL2,
        scenes=[scene],
        scenes_json=tmp_path / "scenes.json",
        asset_manifest=tmp_path / "assets.csv",
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
    )
    assert len(tokens) == 1
    found = find_scene(
        tmp_path,
        tokens[0],
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
    )
    assert found is not None
    loaded, record = found
    assert loaded.product_id == scene.product_id
    assert record["provider"] == "test"
    assert record["owner_user_id"] == OWNER_USER_ID
    assert record["owner_chat_id"] == OWNER_CHAT_ID
    assert (
        find_scene(
            tmp_path,
            tokens[0],
            owner_user_id=OWNER_USER_ID + 1,
            owner_chat_id=OWNER_CHAT_ID,
        )
        is None
    )


def test_parse_scene_helpers():
    assert parse_scene_sensor("s1", Sensor.AUTO) == Sensor.SENTINEL1
    assert parse_scene_sensor("s2", Sensor.AUTO) == Sensor.SENTINEL2
    assert parse_scene_hours(None) == 12
    assert parse_scene_hours("24") == 24
