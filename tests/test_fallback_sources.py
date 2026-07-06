from datetime import datetime, timezone
from pathlib import Path

import pytest

from marine_track.data_sources.base import SceneProvider, SearchRequest, SourceManager
from marine_track.models import Scene, Sensor


class FailingProvider(SceneProvider):
    name = "failing"
    supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest):
        raise RuntimeError("provider is down")


class EmptyProvider(SceneProvider):
    name = "empty"
    supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest):
        return []


class WorkingProvider(SceneProvider):
    name = "working"
    supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest):
        return [
            Scene(
                provider=self.name,
                sensor=Sensor.SENTINEL1,
                product_id="scene-1",
                acquisition_time=request.start,
            )
        ]


def test_fallback_skips_failed_and_empty_provider():
    manager = SourceManager([FailingProvider(), EmptyProvider(), WorkingProvider()])
    request = SearchRequest(
        aoi_geojson_path=Path("dummy.geojson"),
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 2, tzinfo=timezone.utc),
        sensor=Sensor.SENTINEL1,
    )
    provider, scenes = manager.search_first_available(request)
    assert provider == "working"
    assert scenes[0].product_id == "scene-1"


def test_fallback_raises_when_no_scenes():
    manager = SourceManager([EmptyProvider()])
    request = SearchRequest(
        aoi_geojson_path=Path("dummy.geojson"),
        start=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end=datetime(2026, 7, 2, tzinfo=timezone.utc),
        sensor=Sensor.SENTINEL1,
    )
    with pytest.raises(RuntimeError):
        manager.search_first_available(request)
