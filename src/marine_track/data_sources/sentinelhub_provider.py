from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.provider_auth import bearer_headers, request_json, sentinelhub_access_token

SENTINELHUB_COLLECTIONS = {
    Sensor.SENTINEL1: "sentinel-1-grd",
    Sensor.SENTINEL2: "sentinel-2-l2a",
}


class SentinelHubProvider(SceneProvider):
    """Sentinel Hub Catalog API provider.

    Catalog results are search/preview capable unless they expose an explicit
    GeoTIFF/COG asset. No processable raster is invented from metadata links.
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
        scenes = [
            self._feature_to_scene(feature, request.sensor)
            for feature in features
            if isinstance(feature, dict)
        ]
        return sorted(scenes, key=lambda item: (item.acquisition_time, item.product_id), reverse=True)

    def _feature_to_scene(self, feature: dict[str, Any], sensor: Sensor) -> Scene:
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            props = {}
        records = _collect_assets(feature, sensor)
        hrefs = {key: record.href for key, record in records.items()}
        return Scene(
            provider=self.name,
            sensor=sensor,
            product_id=str(feature.get("id") or props.get("id") or "unknown"),
            acquisition_time=_parse_datetime(props.get("datetime") or props.get("start_datetime")),
            footprint_wkt=None,
            download_url=next(iter(hrefs.values()), None),
            assets=hrefs,
            asset_records=records,
            cloud_cover=props.get("eo:cloud_cover"),
            polarizations=_parse_polarizations(props.get("sar:polarizations")),
            beam_mode=props.get("sar:instrument_mode"),
            metadata={"properties": props, "geometry": feature.get("geometry")},
        )


def _collect_assets(feature: dict[str, Any], sensor: Sensor) -> dict[str, SceneAsset]:
    output: dict[str, SceneAsset] = {}
    assets = feature.get("assets") or {}
    if isinstance(assets, dict):
        for key, raw in assets.items():
            if not isinstance(raw, dict) or not isinstance(raw.get("href"), str):
                continue
            roles = raw.get("roles") if isinstance(raw.get("roles"), list) else []
            output[str(key)] = SceneAsset(
                href=str(raw["href"]),
                media_type=str(raw.get("type")) if raw.get("type") else None,
                roles=[str(item) for item in roles],
                title=str(raw.get("title")) if raw.get("title") else None,
                polarization=_key_polarization(str(key)) if sensor == Sensor.SENTINEL1 else None,
                band=str(key).upper() if sensor == Sensor.SENTINEL2 and str(key).lower().startswith("b") else None,
                auth_mode="bearer",
                alternate_hrefs=_alternate_hrefs(raw.get("alternate")),
                extra={"catalog_only": False},
            )
    for link in feature.get("links") or []:
        if not isinstance(link, dict):
            continue
        rel = str(link.get("rel") or "").lower()
        href = link.get("href")
        if isinstance(href, str) and rel in {"thumbnail", "preview", "overview"}:
            output.setdefault(
                rel,
                SceneAsset(
                    href=href,
                    media_type=str(link.get("type")) if link.get("type") else None,
                    roles=[rel],
                    auth_mode="bearer",
                    extra={"catalog_only": True},
                ),
            )
    return output


def _alternate_hrefs(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, str] = {}
    for key, raw in value.items():
        if isinstance(raw, str):
            output[str(key)] = raw
        elif isinstance(raw, dict) and isinstance(raw.get("href"), str):
            output[str(key)] = str(raw["href"])
    return output


def _key_polarization(key: str) -> str | None:
    lowered = key.lower()
    for value in ("vv", "vh", "hh", "hv"):
        if value in lowered:
            return value.upper()
    return None


def _aoi_geometry(aoi: dict[str, Any]) -> dict[str, Any]:
    if aoi.get("type") == "FeatureCollection":
        features = [item for item in aoi.get("features", []) if isinstance(item, dict)]
        if not features:
            raise ValueError("AOI FeatureCollection has no features")
        return features[0]["geometry"]
    if aoi.get("type") == "Feature":
        return aoi["geometry"]
    return aoi


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
