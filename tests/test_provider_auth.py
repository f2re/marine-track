import os

from marine_track.provider_auth import bearer_headers, env_first


def test_env_first_returns_first_defined(monkeypatch):
    monkeypatch.delenv("A", raising=False)
    monkeypatch.setenv("B", "value")
    assert env_first("A", "B") == "value"


def test_bearer_headers():
    assert bearer_headers(None) == {}
    assert bearer_headers("token") == {"Authorization": "Bearer token"}
