from pathlib import Path

import pytest

from marine_track.models import Sensor
from marine_track.telegram_config import load_telegram_config, parse_admin_ids


def clear_telegram_env(monkeypatch):
    for key in (
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ADMIN_IDS",
        "MARINE_TRACK_ALLOW_PUBLIC_BOT",
        "MARINE_TRACK_DEFAULT_AOI",
        "MARINE_TRACK_OUTPUT_DIR",
        "MARINE_TRACK_DEFAULT_SENSOR",
    ):
        monkeypatch.delenv(key, raising=False)


def test_empty_token_has_clear_error(monkeypatch):
    clear_telegram_env(monkeypatch)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN is empty"):
        load_telegram_config()


def test_telegram_bot_token_is_read(monkeypatch):
    clear_telegram_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", " 123:abc ")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "10, 20")

    config = load_telegram_config()

    assert config.token == "123:abc"
    assert config.admin_ids == {10, 20}
    assert config.allow_public_access is False


def test_admin_ids_parser_accepts_commas_semicolons_and_spaces():
    assert parse_admin_ids("123, 456;789") == {123, 456, 789}


def test_admin_ids_parser_rejects_invalid_values():
    with pytest.raises(RuntimeError, match="non-integer"):
        parse_admin_ids("123 bad")


def test_public_mode_requires_explicit_boolean(monkeypatch):
    clear_telegram_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "yes")

    assert load_telegram_config().allow_public_access is True

    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "invalid")
    with pytest.raises(RuntimeError, match="must be boolean"):
        load_telegram_config()


def test_paths_and_sensor_are_loaded(monkeypatch):
    clear_telegram_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson")
    monkeypatch.setenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_SENSOR", "sentinel1")

    config = load_telegram_config()

    assert config.default_aoi == Path("data/aoi/example_black_sea.geojson")
    assert config.output_dir == Path("runs/telegram")
    assert config.default_sensor == Sensor.SENTINEL1
