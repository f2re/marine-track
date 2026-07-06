from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, Sensor
from marine_track.provider_auth import bearer_headers, cdse_access_token

PREVIEW_LINK_RELS = {"thumbnail", "preview", "overview", "alternate"}


class STACProvider(SceneProvider):
    def __init__(
        self,
        name: str,
        api_url: str,
        collections: dict[Sensor, list[str]],
        headers_provider: Callable[[], dict[str, str]] | None = None,
    ):
        self.name = name
        self.api_url = api_url
        self.collections = collections
        self.headers_provider = headers_provider
        self.supported_sensors = set(collections)

    def search(self, request: SearchRequest) -> list[Scene]:
        try:
            from pystac_client import Client
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("pystac-client is not installed") from exc

        with request.aoi_geojson_path.open("r", encoding="utf-8") as f:
            aoi = json.load(f)

        geometry = _aoi_geometry(aoi)
        interval = f"{request.start.isoformat()}/{request.end.isoformat()}"
        headers = self.headers_provider() if self.headers_provider else None

        client = Client.open(self.api_url, headers=headers)
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

        assets = _collect_item_assets(item)

        return Scene(
            provider=self.name,
            sensor=sensor,
            product_id=item.id,
            acquisition_time=acquisition_time,
            footprint_wkt=None,
            download_url=next(iter(assets.values()), None),
            assets=assets,
            cloud_cover=props.get("eo:cloud_cover"),
            polarizations=_parse_polarizations(props.get("sar:polarizations")),
            beam_mode=props.get("sar:instrument_mode"),
            metadata=dict(props),
        )


def _collect_item_assets(item: Any) -> dict[str, str]:
    assets: dict[str, str] = {}
    for key, asset in item.assets.items():
        href = getattr(asset, "href", None)
        if href:
            assets[key] = href

    for link in getattr(item, "links", []) or []:
        rel = str(getattr(link, "rel", "") or "").lower()
        href = getattr(link, "href", None)
        if not href or rel not in PREVIEW_LINK_RELS:
            continue
        key = rel
        media_type = str(getattr(link, "media_type", "") or "").lower()
        title = str(getattr(link, "title", "") or "").lower()
        if "thumbnail" in title or "thumbnail" in media_type:
            key = "thumbnail"
        elif "preview" in title:
            key = "preview"
        assets.setdefault(key, href)
    return assets


def _aoi_geometry(aoi: dict[str, Any]) -> dict[str, Any]:
    if aoi.get("type") == "FeatureCollection":
        return aoi["features"][0]["geometry"]
    if aoi.get("type") == "Feature":
        return aoi["geometry"]
    return aoi


def _parse_polarizations(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.replace("+", ",").split(",") if part.strip()]
    return [str(value)]


def cdse_headers() -> dict[str, str]:
    return bearer_headers(cdse_access_token())


def default_stac_providers() -> list[STACProvider]:
    return [
        STACProvider(
            name="copernicus_cdse",
            api_url="https://catalogue.dataspace.copernicus.eu/stac",
            collections={
                Sensor.SENTINEL1: ["SENTINEL-1"],
                Sensor.SENTINEL2: ["SENTINEL-2"],
            },
            headers_provider=cdse_headers,
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
