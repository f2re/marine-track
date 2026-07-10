from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.provider_auth import bearer_headers, cdse_access_token

PREVIEW_LINK_RELS = {"thumbnail", "preview", "overview"}


class STACProvider(SceneProvider):
    def __init__(
        self,
        name: str,
        api_url: str,
        collections: dict[Sensor, list[str]],
        headers_provider=None,
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

        with request.aoi_geojson_path.open("r", encoding="utf-8") as file_obj:
            aoi = json.load(file_obj)

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
        scenes = [self._item_to_scene(item, request.sensor) for item in search.items()]
        return sorted(
            scenes,
            key=lambda scene: (scene.acquisition_time, scene.product_id),
            reverse=True,
        )

    def _item_to_scene(self, item: Any, sensor: Sensor) -> Scene:
        props = item.properties or {}
        dt = props.get("datetime") or props.get("start_datetime")
        if isinstance(dt, str):
            acquisition_time = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        else:
            acquisition_time = item.datetime

        records = _collect_item_assets(item, provider=self.name, sensor=sensor)
        hrefs = {key: record.href for key, record in records.items()}
        return Scene(
            provider=self.name,
            sensor=sensor,
            product_id=item.id,
            acquisition_time=acquisition_time,
            footprint_wkt=None,
            download_url=next(iter(hrefs.values()), None),
            assets=hrefs,
            asset_records=records,
            cloud_cover=props.get("eo:cloud_cover"),
            polarizations=_parse_polarizations(props.get("sar:polarizations")),
            beam_mode=props.get("sar:instrument_mode"),
            metadata={**dict(props), "collection": getattr(item, "collection_id", None)},
        )


def _collect_item_assets(item: Any, *, provider: str, sensor: Sensor) -> dict[str, SceneAsset]:
    output: dict[str, SceneAsset] = {}
    for key, asset in item.assets.items():
        href = getattr(asset, "href", None)
        if not href:
            continue
        extra = dict(getattr(asset, "extra_fields", None) or {})
        roles = [str(value) for value in (getattr(asset, "roles", None) or extra.get("roles") or [])]
        media_type = getattr(asset, "media_type", None) or extra.get("type")
        bands = extra.get("raster:bands") or extra.get("eo:bands") or []
        first_band = bands[0] if isinstance(bands, list) and bands and isinstance(bands[0], dict) else {}
        alternates = _alternate_hrefs(extra.get("alternate"))
        sidecars = _sidecars(extra)
        band = _first_value(first_band, "common_name", "name", "id")
        polarization = _asset_polarization(str(key), extra, sensor)
        auth_mode = "runtime_signing" if provider == "planetary_computer" else "bearer" if provider in {"copernicus_cdse", "sentinelhub"} else "public"
        output[str(key)] = SceneAsset(
            href=str(href),
            media_type=str(media_type) if media_type else None,
            roles=roles,
            title=getattr(asset, "title", None),
            band=str(band) if band else None,
            polarization=polarization,
            units=_first_value(first_band, "unit", "units") or extra.get("units"),
            nodata=_numeric(_first_value(first_band, "nodata")),
            scale=_numeric(_first_value(first_band, "scale")),
            offset=_numeric(_first_value(first_band, "offset")),
            auth_mode=auth_mode,
            alternate_hrefs=alternates,
            sidecars=sidecars,
            extra={
                "file:size": extra.get("file:size"),
                "checksum:multihash": extra.get("checksum:multihash"),
            },
        )

    for link in getattr(item, "links", []) or []:
        rel = str(getattr(link, "rel", "") or "").lower()
        href = getattr(link, "href", None)
        if not href or rel not in PREVIEW_LINK_RELS:
            continue
        key = rel
        title = str(getattr(link, "title", "") or "")
        media_type = str(getattr(link, "media_type", "") or "") or None
        if "thumbnail" in title.lower():
            key = "thumbnail"
        output.setdefault(
            key,
            SceneAsset(
                href=str(href),
                media_type=media_type,
                roles=["thumbnail" if key == "thumbnail" else "overview"],
                title=title or None,
                auth_mode="public",
            ),
        )
    return output


def _alternate_hrefs(value: Any) -> dict[str, str]:
    output: dict[str, str] = {}
    if not isinstance(value, dict):
        return output
    for key, raw in value.items():
        if isinstance(raw, str):
            output[str(key)] = raw
        elif isinstance(raw, dict) and isinstance(raw.get("href"), str):
            output[str(key)] = str(raw["href"])
    return output


def _sidecars(extra: dict[str, Any]) -> dict[str, str]:
    output: dict[str, str] = {}
    for key in ("calibration", "noise", "metadata", "manifest", "product"):
        value = extra.get(key)
        if isinstance(value, str):
            output[key] = value
        elif isinstance(value, dict) and isinstance(value.get("href"), str):
            output[key] = str(value["href"])
    return output


def _asset_polarization(key: str, extra: dict[str, Any], sensor: Sensor) -> str | None:
    raw = extra.get("sar:polarizations") or extra.get("polarization")
    if isinstance(raw, list) and raw:
        return str(raw[0]).upper()
    if isinstance(raw, str) and raw:
        return raw.upper()
    if sensor == Sensor.SENTINEL1:
        lowered = key.lower()
        for value in ("vv", "vh", "hh", "hv"):
            if value in lowered:
                return value.upper()
    return None


def _aoi_geometry(aoi: dict[str, Any]) -> dict[str, Any]:
    if aoi.get("type") == "FeatureCollection":
        geometries = [
            feature.get("geometry")
            for feature in aoi.get("features", [])
            if isinstance(feature, dict) and isinstance(feature.get("geometry"), dict)
        ]
        if not geometries:
            raise ValueError("AOI FeatureCollection has no geometries")
        if len(geometries) == 1:
            return geometries[0]
        try:
            from shapely.geometry import mapping, shape
            from shapely.ops import unary_union

            return mapping(unary_union([shape(geometry) for geometry in geometries]))
        except Exception:
            return {"type": "GeometryCollection", "geometries": geometries}
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


def _first_value(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", []):
            return value
    return None


def _numeric(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def cdse_headers() -> dict[str, str]:
    return bearer_headers(cdse_access_token())


def default_stac_providers() -> list[STACProvider]:
    cdse_url = os.getenv("CDSE_STAC_URL", "https://stac.dataspace.copernicus.eu/v1/")
    cdse_s1 = os.getenv("CDSE_STAC_SENTINEL1_COLLECTION", "sentinel-1-grd")
    cdse_s2 = os.getenv("CDSE_STAC_SENTINEL2_COLLECTION", "sentinel-2-l2a")
    return [
        STACProvider(
            name="copernicus_cdse",
            api_url=cdse_url,
            collections={
                Sensor.SENTINEL1: [cdse_s1],
                Sensor.SENTINEL2: [cdse_s2],
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
            collections={Sensor.SENTINEL2: ["sentinel-2-l2a"]},
        ),
    ]
