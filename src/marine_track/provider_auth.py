from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OAuthClientCredentials:
    token_url: str
    client_id: str
    client_secret: str | None = None
    username: str | None = None
    password: str | None = None
    scope: str | None = None


def env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def bearer_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def request_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    data: bytes | None = None
    request_headers = {"User-Agent": "marine-track/0.1", **(headers or {})}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(url, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        text = response.read().decode("utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected JSON object from {url}")
    return parsed


def form_post_json(url: str, form: dict[str, str], timeout: int = 120) -> dict[str, Any]:
    data = urlencode(form).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={
            "User-Agent": "marine-track/0.1",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        text = response.read().decode("utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"Expected OAuth JSON object from {url}")
    return parsed


def oauth_token(credentials: OAuthClientCredentials) -> str:
    if credentials.username and credentials.password:
        form = {
            "grant_type": "password",
            "client_id": credentials.client_id,
            "username": credentials.username,
            "password": credentials.password,
        }
        if credentials.client_secret:
            form["client_secret"] = credentials.client_secret
    else:
        form = {
            "grant_type": "client_credentials",
            "client_id": credentials.client_id,
        }
        if credentials.client_secret:
            form["client_secret"] = credentials.client_secret
    if credentials.scope:
        form["scope"] = credentials.scope
    payload = form_post_json(credentials.token_url, form)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"OAuth token response from {credentials.token_url} has no access_token")
    return token


def cdse_access_token() -> str | None:
    explicit = env_first("CDSE_ACCESS_TOKEN")
    if explicit:
        return explicit
    username = env_first("CDSE_USERNAME")
    password = env_first("CDSE_PASSWORD")
    if not username or not password:
        return None
    token_url = env_first(
        "CDSE_TOKEN_URL",
        "COPERNICUS_DATASPACE_TOKEN_URL",
    ) or "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    client_id = env_first("CDSE_CLIENT_ID") or "cdse-public"
    client_secret = env_first("CDSE_CLIENT_SECRET")
    return oauth_token(
        OAuthClientCredentials(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
        )
    )


def sentinelhub_access_token() -> str | None:
    explicit = env_first("SENTINELHUB_ACCESS_TOKEN", "SH_ACCESS_TOKEN")
    if explicit:
        return explicit
    client_id = env_first("SENTINELHUB_CLIENT_ID", "SH_CLIENT_ID")
    client_secret = env_first("SENTINELHUB_CLIENT_SECRET", "SH_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    token_url = env_first("SENTINELHUB_TOKEN_URL", "SH_TOKEN_URL") or "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token"
    return oauth_token(
        OAuthClientCredentials(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
        )
    )
