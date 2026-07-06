from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, Sensor


class STACProvider(SceneProvider):
    def __init__(self, name: str, api_url: str, collections: dict[Sensor, list[str]]):
        self.name = name
        self.api_url = api_url
        self.collections = collections
        self.supported_sensors = set(collections)

    def search(self, request: SearchRequest) -> list[Scene]:
        try:
            from pystac_client import Client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("pystac-client is not installed") from exc

        with request.aoi_geojson_path.open("r", encoding="utf-8") as f:
            aoi = json.load(f)

        geometry = aoi["features"][0]["geometry"] if aoi.get("type") == "FeatureCollection" else aoi["geometry"]
        interval = f"{request.start.isoformat()}/{request.end.isoformat()}"

        client = Client.open(self.api_url)
        search = client.search(
            collections=self.collections[request.sensor],
            intersects=geometry,
            datetime=interval,
            max_items=request.max_results,
        )
        items = list(search.items())

        return [self._item_to_scene(item, request.sensor) for item in items]

    def _item_to_scene(self, item: Any, sensor: Sensor) -> Scene:
        props = item.properties or {}
        dt = props.get("datetime") or props.get("start_datetime")
        if isinstance(dt, str):
            acquisition_time = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        else:
            acquisition_time = item.datetime
        return Scene(
            provider=self.name,
            sensor=sensor,
            product_id=item.id,
            acquisition_time=acquisition_time,
            footprint_wkt=None,
            download_url=None,
            cloud_cover=props.get("eo:cloud_cover"),
            polarization=props.get("sar:polarizations"),
            beam_mode=props.get("sar:instrument_mode"),
            metadata=dict(props),
        )


def default_stac_providers() -> list[STACProvider]:
    return [
        STACProvider(
            name="copernicus_cdse",
            api_url="https://catalogue.dataspace.copernicus.eu/stac",
            collections={
                Sensor.SENTINEL1: ["SENTINEL-1"],
                Sensor.SENTINEL2: ["SENTINEL-2"],
            },
        ),
        STACProvider(
            name="planetary_computer",
            api_url="https://planetarycomputer.microsoft.com/api/stac/v1",
            collections={
                Sensor.SENTINEL1: ["sentinel-1-rtc"],
                Sensor.SENTINEL2: ["sentinel-2-l2a"],
            },
        ),
        STACProvider(
            name="earthsearch",
            api_url="https://earth-search.aws.element84.com/v1",
            collections={
                Sensor.SENTINEL2: ["sentinel-2-l2a"],
            },
        ),
    ]
