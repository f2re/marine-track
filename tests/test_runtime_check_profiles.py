import runtime_check


def test_provider_profile_alias(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "none")
    assert runtime_check.provider_profile() == "core"


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

    assert "MARINE_TRACK_MAX_RESULTS must be integer" in errors[0]
