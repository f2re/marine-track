from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from marine_track.cache_policy import search_cache_key
from marine_track.models import Scene, Sensor
from marine_track.telegram_config import load_telegram_config
from marine_track.telegram_scene_browser import (
    find_scene,
    register_scenes,
    restore_scene_page,
    scene_token,
)


def test_telegram_access_is_fail_closed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
    monkeypatch.delenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", raising=False)
    config = load_telegram_config()

    import marine_track.telegram_bot as telegram_bot

    monkeypatch.setattr(telegram_bot, "CONFIG", config)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=12345))
    assert telegram_bot.is_authorized(update) is False


def test_public_access_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.delenv("TELEGRAM_ADMIN_IDS", raising=False)
    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "1")
    config = load_telegram_config()

    import marine_track.telegram_bot as telegram_bot

    monkeypatch.setattr(telegram_bot, "CONFIG", config)
    update = SimpleNamespace(effective_user=SimpleNamespace(id=12345))
    assert telegram_bot.is_authorized(update) is True


def test_invalid_admin_id_is_rejected(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123,not-a-number")
    with pytest.raises(RuntimeError, match="non-integer"):
        load_telegram_config()


def test_search_cache_key_uses_absolute_window_and_capability(tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    start = datetime(2026, 7, 10, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=12)
    base = search_cache_key(
        aoi, start, end, Sensor.SENTINEL1, 10, purpose="catalog", capability="any_scene"
    )
    shifted = search_cache_key(
        aoi,
        start + timedelta(hours=1),
        end + timedelta(hours=1),
        Sensor.SENTINEL1,
        10,
        purpose="catalog",
        capability="any_scene",
    )
    detection = search_cache_key(
        aoi,
        start,
        end,
        Sensor.SENTINEL1,
        10,
        purpose="detection",
        capability="processable_geotiff_cog",
    )
    assert base != shifted
    assert base != detection


def test_scene_tokens_and_registry_are_user_chat_scoped(tmp_path):
    scene = Scene(
        provider="test",
        sensor=Sensor.SENTINEL1,
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": "https://example.invalid/scene.tif"},
    )
    scenes_json = tmp_path / "scenes.json"
    scenes_json.write_text(
        json.dumps([scene.model_dump(mode="json")], default=str), encoding="utf-8"
    )
    tokens = register_scenes(
        tmp_path,
        "test",
        Sensor.SENTINEL1,
        [scene],
        scenes_json,
        None,
        owner_user_id=100,
        owner_chat_id=200,
    )
    token = tokens[0]
    assert token == scene_token(scene, 100, 200)
    assert token != scene_token(scene, 101, 200)
    assert find_scene(tmp_path, token, owner_user_id=100, owner_chat_id=200) is not None
    assert find_scene(tmp_path, token, owner_user_id=101, owner_chat_id=200) is None
    assert find_scene(tmp_path, token, owner_user_id=100, owner_chat_id=201) is None

    page = restore_scene_page(
        tmp_path, token, 0, owner_user_id=100, owner_chat_id=200
    )
    assert page.tokens == [token]
    with pytest.raises(FileNotFoundError):
        restore_scene_page(
            tmp_path, token, 0, owner_user_id=101, owner_chat_id=200
        )
