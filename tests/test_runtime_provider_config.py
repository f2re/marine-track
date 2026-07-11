from __future__ import annotations

import runtime_check


def _clear_provider_env(monkeypatch) -> None:
    for name in (
        "SENTINELHUB_ACCESS_TOKEN",
        "SENTINELHUB_CLIENT_ID",
        "SENTINELHUB_CLIENT_SECRET",
        "SH_ACCESS_TOKEN",
        "SH_CLIENT_ID",
        "SH_CLIENT_SECRET",
        "CDSE_ACCESS_TOKEN",
        "CDSE_CLIENT_ID",
        "CDSE_CLIENT_SECRET",
        "CDSE_USERNAME",
        "CDSE_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)


def test_empty_optional_provider_credentials_are_valid(monkeypatch) -> None:
    _clear_provider_env(monkeypatch)

    assert runtime_check.check_optional_provider_credentials() == []


def test_incomplete_sentinelhub_pair_is_rejected(monkeypatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("SENTINELHUB_CLIENT_ID", "configured")

    errors = runtime_check.check_optional_provider_credentials()

    assert len(errors) == 1
    assert "Sentinel Hub OAuth is incomplete" in errors[0]


def test_explicit_sentinelhub_token_does_not_require_client_pair(monkeypatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("SENTINELHUB_ACCESS_TOKEN", "token")
    monkeypatch.setenv("SENTINELHUB_CLIENT_ID", "unused")

    assert runtime_check.check_optional_provider_credentials() == []


def test_incomplete_cdse_password_pair_is_rejected(monkeypatch) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("CDSE_USERNAME", "configured")

    errors = runtime_check.check_optional_provider_credentials()

    assert len(errors) == 1
    assert "CDSE password OAuth is incomplete" in errors[0]


def test_detection_runtime_bounds_reject_unbounded_values(monkeypatch) -> None:
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_DETECTION_SIDE_KM", "20")
    monkeypatch.setenv("MARINE_TRACK_DETECTION_JOB_TIMEOUT_S", "0")

    errors = runtime_check.check_detection_runtime_bounds()

    assert any("DEFAULT_DETECTION_SIDE_KM" in item for item in errors)
    assert any("DETECTION_JOB_TIMEOUT_S" in item for item in errors)
