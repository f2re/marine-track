from __future__ import annotations

import json
from datetime import datetime

from shapely.geometry import shape

from marine_track.data_sources.base import SceneProvider, SearchRequest
from marine_track.models import Scene, Sensor

ASF_PREVIEW_KEYS = ("browse", "browseURL", "browseUrl", "thumbnail", "thumbnailUrl", "preview")


class ASFProvider(SceneProvider):
    """NASA ASF provider for Sentinel-1 SAR scenes.

    Uses the optional `asf_search` dependency. Import is delayed so the package can be
    installed and tested without configured Earthdata credentials.
    """

    name = "asf"
    supported_sensors = {Sensor.SENTINEL1}

    def search(self, request: SearchRequest) -> list[Scene]:
        try:
            import asf_search as asf
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("asf_search is not installed") from exc

        with request.aoi_geojson_path.open("r", encoding="utf-8") as f:
            aoi = json.load(f)
        geometry = aoi["features"][0]["geometry"] if aoi.get("type") == "FeatureCollection" else aoi["geometry"]
        geom = shape(geometry)

        results = asf.geo_search(
            platform=[asf.PLATFORM.SENTINEL1],
            processingLevel=[asf.PRODUCT_TYPE.GRD_HD],
            intersectsWith=geom.wkt,
            start=request.start,
            end=request.end,
            maxResults=request.max_results,
        )

        scenes: list[Scene] = []
        for product in results:
            props = product.properties
            download_url = props.get("url")
            assets = _collect_asf_assets(props, download_url)
            scenes.append(
                Scene(
                    provider=self.name,
                    sensor=Sensor.SENTINEL1,
                    product_id=props.get("sceneName") or props.get("fileID") or "unknown",
                    acquisition_time=_parse_datetime(props.get("startTime")),
                    footprint_wkt=props.get("stringFootprint"),
                    download_url=download_url,
                    assets=assets,
                    polarizations=_parse_polarizations(props.get("polarization")),
                    beam_mode=props.get("beamModeType"),
                    metadata=dict(props),
                )
            )
        return scenes


def _collect_asf_assets(props: dict, download_url: object) -> dict[str, str]:
    assets: dict[str, str] = {}
    for key in ASF_PREVIEW_KEYS:
        value = props.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            assets.setdefault(key, value)
    if isinstance(download_url, str) and download_url:
        assets.setdefault("product", download_url)
    return assets


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise ValueError(f"Unsupported datetime value: {value!r}")


def _parse_polarizations(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.replace("+", ",").split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
