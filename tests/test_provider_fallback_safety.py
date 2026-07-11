from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.detection_scene_search import search_detection_capable_scenes
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.provider_auth import (
    cdse_credentials_configured,
    sentinelhub_credentials_configured,
)
from marine_track.resource_limits import ResourceLimitError


class EmptyProvider(SceneProvider):
    def __init__(self, name: str, calls: list[str]):
        self.name = name
        self.calls = calls
        self.supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest) -> list[Scene]:
        del request
        self.calls.append(self.name)
        return []


class PlanetaryProvider(SceneProvider):
    name = "planetary_computer"
    supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest) -> list[Scene]:
        return [
            Scene(
                provider=self.name,
                sensor=request.sensor,
                product_id="tokenless-scene",
                acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
                asset_records={
                    "vv": SceneAsset(
                        href="https://example.test/scene.tif",
                        media_type="image/tiff; application=geotiff",
                        polarization="VV",
                        auth_mode="runtime_signing",
                    )
                },
            )
        ]


def _clear_provider_credentials(monkeypatch) -> None:
    for name in (
        "CDSE_ACCESS_TOKEN",
        "CDSE_USERNAME",
        "CDSE_PASSWORD",
        "CDSE_CLIENT_ID",
        "CDSE_CLIENT_SECRET",
        "SENTINELHUB_ACCESS_TOKEN",
        "SENTINELHUB_CLIENT_ID",
        "SENTINELHUB_CLIENT_SECRET",
        "SH_ACCESS_TOKEN",
        "SH_CLIENT_ID",
        "SH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def _write_aoi(path, west: float, south: float, east: float, north: float) -> None:
    path.write_text(
        "{\"type\":\"Polygon\",\"coordinates\":[[["
        f"{west},{south}],[{east},{south}],[{east},{north}],[{west},{north}],[{west},{south}"
        "]]}",
        encoding="utf-8",
    )


def test_credential_preflight_requires_complete_optional_pairs(monkeypatch) -> None:
    _clear_provider_credentials(monkeypatch)
    assert cdse_credentials_configured() is False
    assert sentinelhub_credentials_configured() is False

    monkeypatch.setenv("CDSE_CLIENT_ID", "client")
    monkeypatch.setenv("SENTINELHUB_CLIENT_ID", "client")
    assert cdse_credentials_configured() is False
    assert sentinelhub_credentials_configured() is False

    monkeypatch.setenv("CDSE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SENTINELHUB_CLIENT_SECRET", "secret")
    assert cdse_credentials_configured() is True
    assert sentinelhub_credentials_configured() is True


def test_tokenless_planetary_computer_is_used_without_optional_tokens(tmp_path, monkeypatch) -> None:
    _clear_provider_credentials(monkeypatch)
    aoi = tmp_path / "aoi.geojson"
    _write_aoi(aoi, 37.0, 44.0, 37.1, 44.1)
    calls: list[str] = []
    providers = [
        PlanetaryProvider(),
        EmptyProvider("copernicus_cdse", calls),
    ]
    monkeypatch.setattr(
        "marine_track.detection_scene_search.default_stac_providers",
        lambda: providers,
    )

    result = search_detection_capable_scenes(
        aoi,
        datetime(2026, 7, 9, tzinfo=timezone.utc),
        datetime(2026, 7, 11, tzinfo=timezone.utc),
        Sensor.SENTINEL1,
        tmp_path / "out",
        max_results=5,
    )

    assert result.provider == "planetary_computer"
    assert result.scenes[0].product_id == "tokenless-scene"
    assert calls == []


def test_large_detection_aoi_is_rejected_before_provider_network_io(tmp_path, monkeypatch) -> None:
    aoi = tmp_path / "large.geojson"
    _write_aoi(aoi, 36.5, 43.8, 38.5, 45.0)
    provider_called = False

    def forbidden_providers():
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider construction must not run")

    monkeypatch.setattr(
        "marine_track.detection_scene_search.default_stac_providers",
        forbidden_providers,
    )
    monkeypatch.setenv("MARINE_TRACK_MAX_DETECTION_AOI_AREA_KM2", "400")

    with pytest.raises(ResourceLimitError, match="exceeds configured limit"):
        search_detection_capable_scenes(
            aoi,
            datetime(2026, 7, 9, tzinfo=timezone.utc),
            datetime(2026, 7, 11, tzinfo=timezone.utc),
            Sensor.SENTINEL1,
            tmp_path / "out",
        )
    assert provider_called is False
