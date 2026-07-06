from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, Sensor
from marine_track.provider_auth import bearer_headers, request_json, sentinelhub_access_token

SENTINELHUB_COLLECTIONS = {
    Sensor.SENTINEL1: "sentinel-1-grd",
    Sensor.SENTINEL2: "sentinel-2-l2a",
}


class SentinelHubProvider(SceneProvider):
    """Sentinel Hub Catalog API provider.

    This is a real Catalog/STAC access provider. It requires Sentinel Hub OAuth
    credentials for protected endpoints. It intentionally does not invent direct COG
    assets; only assets/links returned by the Catalog response are exposed.
    """

    name = "sentinelhub"
    supported_sensors = {Sensor.SENTINEL1, Sensor.SENTINEL2}

    def __init__(self, catalog_url: str | None = None):
        self.catalog_url = catalog_url or os.getenv(
            "SENTINELHUB_CATALOG_URL",
            "https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search",
        )

    def search(self, request: SearchRequest) -> list[Scene]:
        token = sentinelhub_access_token()
        if not token:
            raise RuntimeError(
                "Sentinel Hub credentials are required: set SENTINELHUB_CLIENT_ID "
                "and SENTINELHUB_CLIENT_SECRET, or SENTINELHUB_ACCESS_TOKEN"
            )
        with request.aoi_geojson_path.open("r", encoding="utf-8") as file_obj:
            aoi = json.load(file_obj)
        payload = {
            "collections": [SENTINELHUB_COLLECTIONS[request.sensor]],
            "intersects": _aoi_geometry(aoi),
            "datetime": f"{request.start.isoformat()}/{request.end.isoformat()}",
            "limit": request.max_results,
        }
        response = request_json(
            self.catalog_url,
            method="POST",
            payload=payload,
            headers=bearer_headers(token),
        )
        features = response.get("features") or []
        if not isinstance(features, list):
            return []
        return [self._feature_to_scene(feature, request.sensor) for feature in features if isinstance(feature, dict)]

    def _feature_to_scene(self, feature: dict[str, Any], sensor: Sensor) -> Scene:
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        dt = props.get("datetime") or props.get("start_datetime")
        acquisition_time = _parse_datetime(dt)
        assets = _collect_assets(feature)
        geometry = feature.get("geometry")
        return Scene(
            provider=self.name,
            sensor=sensor,
            product_id=str(feature.get("id") or props.get("id") or "unknown"),
            acquisition_time=acquisition_time,
            footprint_wkt=None,
            download_url=next(iter(assets.values()), None),
            assets=assets,
            cloud_cover=props.get("eo:cloud_cover"),
            polarizations=_parse_polarizations(props.get("sar:polarizations")),
            beam_mode=props.get("sar:instrument_mode"),
            metadata={"properties": props, "geometry": geometry},
        )


def _aoi_geometry(aoi: dict[str, Any]) -> dict[str, Any]:
    if aoi.get("type") == "FeatureCollection":
        return aoi["features"][0]["geometry"]
    if aoi.get("type") == "Feature":
        return aoi["geometry"]
    return aoi


def _collect_assets(feature: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    assets = feature.get("assets") or {}
    if isinstance(assets, dict):
        for key, asset in assets.items():
            if isinstance(asset, dict) and isinstance(asset.get("href"), str):
                output[str(key)] = str(asset["href"])
    for link in feature.get("links") or []:
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = link.get("href")
        if isinstance(href, str) and rel in {"thumbnail", "preview", "overview", "alternate"}:
            output.setdefault(rel, href)
    return output


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _parse_polarizations(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.replace("+", ",").split(",") if part.strip()]
    return [str(value)]
