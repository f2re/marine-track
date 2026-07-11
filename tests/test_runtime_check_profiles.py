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


def test_feature_flags_and_lee_window_are_validated(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_ENABLE_WAKE_RESEARCH", "maybe")
    monkeypatch.setenv("MARINE_TRACK_S1_LEE_WINDOW_PX", "4")
    errors = runtime_check.check_feature_flags()
    assert "MARINE_TRACK_ENABLE_WAKE_RESEARCH must be boolean" in errors
    assert "MARINE_TRACK_S1_LEE_WINDOW_PX must be an odd integer >= 3" in errors


def test_feature_flags_allow_unused_lee_window_and_reject_bad_lock_timeout(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_S1_SPECKLE_FILTER", "none")
    monkeypatch.setenv("MARINE_TRACK_S1_LEE_WINDOW_PX", "4")
    monkeypatch.setenv("MARINE_TRACK_RASTER_LOCK_TIMEOUT_S", "nan")
    errors = runtime_check.check_feature_flags()
    assert "MARINE_TRACK_S1_LEE_WINDOW_PX must be an odd integer >= 3" not in errors
    assert "MARINE_TRACK_RASTER_LOCK_TIMEOUT_S must be finite and positive" in errors
