import json
from datetime import datetime, timedelta, timezone

import pytest

from marine_track.models import Scene, Sensor
from marine_track.telegram_scene_browser import (
    PAGE_CALLBACK_PREFIX,
    clamp_page,
    page_count,
    register_scenes,
    restore_scene_page,
    scene_keyboard,
    scene_page_callback_data,
    scene_page_slice,
)


def make_scene(index: int) -> Scene:
    return Scene(
        provider="test-provider",
        sensor=Sensor.SENTINEL1,
        product_id=f"S1_TEST_PRODUCT_{index:02d}_" + "X" * 120,
        acquisition_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
        assets={"preview": f"https://example.test/{index}.jpg"},
        polarizations=["VV", "VH"],
        beam_mode="IW",
    )


def write_scenes(tmp_path, scenes: list[Scene]):
    path = tmp_path / "scenes.json"
    path.write_text(json.dumps([scene.model_dump(mode="json") for scene in scenes]), encoding="utf-8")
    return path


def callback_data(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_scene_page_count_and_slice(tmp_path):
    scenes = [make_scene(index) for index in range(13)]
    tokens = [f"token-{index}" for index in range(13)]

    page_tokens, page_scenes, page, total_pages = scene_page_slice(tokens, scenes, page=2, page_size=6)

    assert page_count(len(scenes), page_size=6) == 3
    assert page == 2
    assert total_pages == 3
    assert page_tokens == ["token-12"]
    assert [scene.product_id for scene in page_scenes] == [scenes[12].product_id]


def test_scene_page_bounds():
    assert clamp_page(-10, total=13, page_size=6) == 0
    assert clamp_page(99, total=13, page_size=6) == 2
    assert clamp_page(0, total=0, page_size=6) == 0


def test_scene_callbacks_are_short(tmp_path):
    scenes = [make_scene(index) for index in range(13)]
    scenes_json = write_scenes(tmp_path, scenes)
    tokens = register_scenes(
        tmp_path,
        "test-provider",
        Sensor.SENTINEL1,
        scenes,
        scenes_json,
        None,
        search_hours=12,
    )

    markup = scene_keyboard(tokens, scenes, page=0, page_size=6)
    callbacks = callback_data(markup)

    assert any(item.startswith(f"{PAGE_CALLBACK_PREFIX}:") for item in callbacks)
    assert all(len(item.encode("utf-8")) <= 64 for item in callbacks)
    assert len(scene_page_callback_data(tokens[0], 2).encode("utf-8")) <= 64


def test_restore_scene_page_from_registry_without_provider_search(tmp_path):
    scenes = [make_scene(index) for index in range(8)]
    scenes_json = write_scenes(tmp_path, scenes)
    tokens = register_scenes(
        tmp_path,
        "test-provider",
        Sensor.SENTINEL1,
        scenes,
        scenes_json,
        None,
        search_hours=24,
    )

    restored = restore_scene_page(tmp_path, tokens[0], page=1, page_size=6)

    assert restored.provider == "test-provider"
    assert restored.sensor == Sensor.SENTINEL1
    assert restored.hours == 24
    assert restored.page == 1
    assert restored.page_count == 2
    assert [scene.product_id for scene in restored.scenes] == [scene.product_id for scene in scenes]
    assert restored.tokens == tokens


def test_restore_scene_page_reports_stale_registry(tmp_path):
    scenes = [make_scene(0)]
    scenes_json = write_scenes(tmp_path, scenes)
    tokens = register_scenes(tmp_path, "test-provider", Sensor.SENTINEL1, scenes, scenes_json, None)
    scenes_json.unlink()

    with pytest.raises(FileNotFoundError):
        restore_scene_page(tmp_path, tokens[0], page=0)
