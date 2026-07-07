import pytest

from marine_track import provider_preflight


def clear_profile(monkeypatch):
    monkeypatch.delenv("MARINE_TRACK_PROVIDER_PROFILE", raising=False)


def test_provider_profile_defaults_to_all(monkeypatch):
    clear_profile(monkeypatch)

    assert provider_preflight.provider_profile() == "all"


def test_provider_profile_rejects_removed_none_alias(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "none")

    with pytest.raises(ValueError, match="invalid MARINE_TRACK_PROVIDER_PROFILE"):
        provider_preflight.provider_profile()


def test_provider_profile_accepts_current_values(monkeypatch):
    for value in ("all", "scene", "aux", "core"):
        monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", value)
        assert provider_preflight.provider_profile() == value


def test_core_profile_skips_provider_checks(monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_PROVIDER_PROFILE", "core")

    assert provider_preflight.run_preflight() == 0
