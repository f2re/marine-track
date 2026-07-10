import pytest

import runtime_check


def test_removed_provider_profile_alias_is_rejected(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "none")

    with pytest.raises(ValueError, match="invalid MARINE_TRACK_PROVIDER_PROFILE"):
        runtime_check.provider_profile()


def test_required_modules_core_skips_provider_packages(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "core")
    modules = runtime_check.required_modules()
    assert "pystac_client" not in modules
    assert "copernicusmarine" not in modules
    assert "marine_track.telegram_bot" in modules


def test_required_modules_all_includes_provider_packages(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "all")
    modules = runtime_check.required_modules()
    assert "pystac_client" in modules
    assert "copernicusmarine" in modules


def test_numeric_env_validation_catches_invalid_values(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_MAX_RESULTS", "not-an-int")
    monkeypatch.setenv("MARINE_TRACK_SCENE_SEARCH_TTL_MIN", "30")

    errors = runtime_check.check_numeric_env()

    assert "MARINE_TRACK_MAX_RESULTS must be numeric" in errors[0]
