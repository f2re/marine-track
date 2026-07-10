from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/marine_track/models.py",
    '''from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


class Sensor(str, Enum):
    AUTO = "auto"
    SENTINEL1 = "sentinel1"
    SENTINEL2 = "sentinel2"


class SpeedMethod(str, Enum):
    NOT_ESTIMATED = "not_estimated"
    SENTINEL2_INTERBAND = "sentinel2_interband_displacement"
    SAR_OFFSET_EXPERIMENTAL = "sar_offset_experimental"
    # Legacy enum values remain readable, but AIS and Kelvin values are no longer
    # written into the operational speed estimate.
    KELVIN_WAVELENGTH = "kelvin_wavelength"
    AIS_SOG = "ais_sog"


class HeadingMethod(str, Enum):
    NOT_ESTIMATED = "not_estimated"
    WAKE_AXIS = "wake_axis"
    HULL_ORIENTATION = "hull_orientation"
    SENTINEL2_INTERBAND = "sentinel2_interband_displacement"
    AIS_COG = "ais_course_over_ground"


class SceneAsset(BaseModel):
    """Typed STAC/provider asset contract.

    Authentication material is never stored here. ``auth_mode`` only describes
    how the materializer must obtain transient request headers or a signed URL.
    """

    href: str
    media_type: str | None = None
    roles: list[str] = Field(default_factory=list)
    title: str | None = None
    band: str | None = None
    polarization: str | None = None
    units: str | None = None
    nodata: float | int | None = None
    scale: float | None = None
    offset: float | None = None
    auth_mode: Literal["public", "bearer", "runtime_signing", "unknown"] = "unknown"
    storage: Literal["https", "http", "s3", "azure", "gs", "local", "unknown"] = "unknown"
    alternate_hrefs: dict[str, str] = Field(default_factory=dict)
    sidecars: dict[str, str] = Field(default_factory=dict)
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"href": value}
        return value

    @model_validator(mode="after")
    def infer_storage(self) -> SceneAsset:
        if self.storage != "unknown":
            return self
        lowered = self.href.lower()
        if lowered.startswith("https://"):
            self.storage = "https"
        elif lowered.startswith("http://"):
            self.storage = "http"
        elif lowered.startswith("s3://"):
            self.storage = "s3"
        elif lowered.startswith(("az://", "azure://")):
            self.storage = "azure"
        elif lowered.startswith("gs://"):
            self.storage = "gs"
        elif "://" not in lowered:
            self.storage = "local"
        return self

    def all_hrefs(self) -> list[tuple[str, str]]:
        output = [("primary", self.href)]
        output.extend((str(key), str(value)) for key, value in self.alternate_hrefs.items() if value)
        return output

    def preferred_href(self, *, prefer_https: bool = False) -> str:
        candidates = self.all_hrefs()
        if prefer_https:
            for _name, href in candidates:
                if href.lower().startswith("https://"):
                    return href
        return self.href


class OperationalSpeed(BaseModel):
    """Own-system operational estimate.

    External AIS values and research-only Kelvin proxies must not populate this
    object. Until an independently validated estimator is available, the value
    remains null and the status remains ``not_estimated``.
    """

    value_knots: float | None = Field(default=None, ge=0.0, le=200.0)
    method: SpeedMethod = SpeedMethod.NOT_ESTIMATED
    status: Literal["not_estimated", "estimated", "rejected"] = "not_estimated"
    uncertainty_knots: float | None = Field(default=None, ge=0.0)
    source: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> OperationalSpeed:
        if self.value_knots is None:
            if self.status == "estimated":
                raise ValueError("estimated operational speed requires value_knots")
            if self.method != SpeedMethod.NOT_ESTIMATED:
                raise ValueError("null operational speed must use method=not_estimated")
        elif self.status != "estimated":
            raise ValueError("non-null operational speed requires status=estimated")
        return self


class KelvinSpeedProxy(BaseModel):
    """Research-only deep-water proxy derived from an experimental wake profile."""

    value_knots: float = Field(ge=0.0)
    value_mps: float = Field(ge=0.0)
    wavelength_m: float = Field(gt=0.0)
    wavelength_px: float = Field(gt=0.0)
    method: Literal["deep_water_kelvin_wavelength"] = "deep_water_kelvin_wavelength"
    experimental: Literal[True] = True
    quality_score: float | None = Field(default=None, ge=0.0, le=1.0)
    assumptions: list[str] = Field(
        default_factory=lambda: [
            "deep_water_dispersion",
            "detected_line_is_ship_wake_axis",
            "profile_peaks_represent_kelvin_wavelength",
        ]
    )


class ResearchProxies(BaseModel):
    kelvin_speed: KelvinSpeedProxy | None = None


class AISReference(BaseModel):
    """External AIS reference; never an implicit ground-truth or own estimate."""

    status: Literal["matched", "ambiguous"]
    mmsi: str
    distance_m: float = Field(ge=0.0)
    ais_lon: float
    ais_lat: float
    sog_knots: float | None = Field(default=None, ge=0.0)
    cog_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    interpolation_gap_s: float = Field(ge=0.0)
    nearest_time_offset_s: float = Field(ge=0.0)
    second_best_distance_m: float | None = Field(default=None, ge=0.0)
    distance_margin_m: float | None = None
    assignment_method: Literal["greedy_one_to_one_distance"] = "greedy_one_to_one_distance"
    reference_quality: Literal["usable", "ambiguous"]
    not_ground_truth: Literal[True] = True
    track: list[dict[str, object]] = Field(default_factory=list)
    source_reference: str | None = None


class DetectionReferences(BaseModel):
    ais: AISReference | None = None


class Scene(BaseModel):
    provider: str
    sensor: Sensor
    product_id: str
    acquisition_time: datetime
    footprint_wkt: str | None = None
    download_url: str | None = None
    # Legacy flat mapping remains available for Telegram/UI and old manifests.
    assets: dict[str, str] = Field(default_factory=dict)
    # Canonical provider/materializer contract.
    asset_records: dict[str, SceneAsset] = Field(default_factory=dict)
    cloud_cover: float | None = None
    polarizations: list[str] | None = None
    beam_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_assets(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy = data.get("assets") or {}
        records = data.get("asset_records") or {}
        normalized_records: dict[str, Any] = {}
        normalized_hrefs: dict[str, str] = {}

        if isinstance(legacy, dict):
            for key, raw in legacy.items():
                if isinstance(raw, str):
                    normalized_hrefs[str(key)] = raw
                    normalized_records[str(key)] = {"href": raw}
                elif isinstance(raw, SceneAsset):
                    normalized_hrefs[str(key)] = raw.href
                    normalized_records[str(key)] = raw
                elif isinstance(raw, dict) and isinstance(raw.get("href"), str):
                    normalized_hrefs[str(key)] = str(raw["href"])
                    normalized_records[str(key)] = raw

        if isinstance(records, dict):
            for key, raw in records.items():
                record = raw if isinstance(raw, SceneAsset) else SceneAsset.model_validate(raw)
                normalized_records[str(key)] = record
                normalized_hrefs[str(key)] = record.href

        data["assets"] = normalized_hrefs
        data["asset_records"] = normalized_records
        if not data.get("download_url") and normalized_hrefs:
            data["download_url"] = next(iter(normalized_hrefs.values()))
        return data

    def asset_record(self, key: str) -> SceneAsset | None:
        record = self.asset_records.get(key)
        if record is not None:
            return record
        href = self.assets.get(key)
        return SceneAsset(href=href) if href else None

    def polarization_label(self) -> str:
        if self.polarizations:
            return ",".join(self.polarizations)
        if self.cloud_cover is not None:
            return f"cloud={self.cloud_cover:.1f}"
        return "-"


class VesselDetection(BaseModel):
    """Georeferenced vessel *candidate*, not a confirmed vessel observation.

    ``confidence`` remains accepted as an input alias for old payloads. New
    serializations expose only ``ranking_score`` and the separated speed,
    research-proxy and external-reference objects.
    """

    detection_id: str
    object_type: Literal["vessel_candidate"] = "vessel_candidate"
    lon: float
    lat: float
    satellite: str
    provider: str
    product_id: str
    acquisition_time: datetime
    ranking_score: float = Field(
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("ranking_score", "confidence"),
    )
    wake_type: str = "unknown"
    heading_deg: float | None = None
    heading_method: HeadingMethod = HeadingMethod.NOT_ESTIMATED
    heading_error_deg: float | None = None
    heading_ambiguity_deg: float | None = None
    speed: OperationalSpeed = Field(default_factory=OperationalSpeed)
    research_proxies: ResearchProxies = Field(default_factory=ResearchProxies)
    references: DetectionReferences = Field(default_factory=DetectionReferences)
    validation_status: str = "unvalidated"
    validation: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def confidence(self) -> float:
        """Compatibility accessor. The value is a ranking score, not probability."""

        return self.ranking_score

    @confidence.setter
    def confidence(self, value: float) -> None:
        self.ranking_score = value

    @property
    def speed_knots(self) -> float | None:
        """Compatibility accessor for the own-system operational estimate only."""

        return self.speed.value_knots

    @property
    def speed_method(self) -> SpeedMethod:
        return self.speed.method

    @property
    def speed_reference(self) -> str | None:
        return self.speed.source

    def to_geojson_feature(self) -> dict[str, Any]:
        props = self.model_dump(mode="json")
        lon = props.pop("lon")
        lat = props.pop("lat")
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        }
''',
)


write(
    "src/marine_track/data_sources/stac_provider.py",
    '''from __future__ import annotations

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
''',
)


write(
    "src/marine_track/data_sources/sentinelhub_provider.py",
    '''from __future__ import annotations

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
''',
)


write(
    "src/marine_track/provider_auth.py",
    '''from __future__ import annotations

import hashlib
import json
import os
import threading
import time
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


_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


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
    cache_key = _credentials_cache_key(credentials)
    now = time.time()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

    if credentials.username and credentials.password:
        form = {
            "grant_type": "password",
            "client_id": credentials.client_id,
            "username": credentials.username,
            "password": credentials.password,
        }
    else:
        form = {"grant_type": "client_credentials", "client_id": credentials.client_id}
    if credentials.client_secret:
        form["client_secret"] = credentials.client_secret
    if credentials.scope:
        form["scope"] = credentials.scope

    payload = form_post_json(credentials.token_url, form)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError(f"OAuth token response from {credentials.token_url} has no access_token")
    expires_in = payload.get("expires_in")
    ttl = float(expires_in) if isinstance(expires_in, (int, float)) else 600.0
    valid_until = now + max(30.0, ttl - min(60.0, ttl * 0.2))
    with _TOKEN_LOCK:
        _TOKEN_CACHE[cache_key] = (token, valid_until)
    return token


def clear_oauth_token_cache() -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def cdse_access_token() -> str | None:
    explicit = env_first("CDSE_ACCESS_TOKEN")
    if explicit:
        return explicit
    username = env_first("CDSE_USERNAME")
    password = env_first("CDSE_PASSWORD")
    client_id = env_first("CDSE_CLIENT_ID") or "cdse-public"
    client_secret = env_first("CDSE_CLIENT_SECRET")
    if not ((username and password) or (client_id and client_secret)):
        return None
    token_url = env_first(
        "CDSE_TOKEN_URL",
        "COPERNICUS_DATASPACE_TOKEN_URL",
    ) or "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
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
    token_url = env_first("SENTINELHUB_TOKEN_URL", "SH_TOKEN_URL") or (
        "https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token"
    )
    return oauth_token(
        OAuthClientCredentials(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
        )
    )


def _credentials_cache_key(credentials: OAuthClientCredentials) -> str:
    payload = "|".join(
        [
            credentials.token_url,
            credentials.client_id,
            credentials.username or "",
            credentials.scope or "",
            credentials.client_secret or "",
            credentials.password or "",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
''',
)


write(
    "src/marine_track/scene_materializer.py",
    '''from __future__ import annotations

import hashlib
import os
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from marine_track.cache_policy import raster_cache_path, touch_cache_file
from marine_track.models import Scene, SceneAsset
from marine_track.provider_auth import bearer_headers, cdse_access_token, sentinelhub_access_token
from marine_track.telegram_scene_browser import find_scene

RASTER_EXTENSIONS = {".tif", ".tiff"}
ARCHIVE_EXTENSIONS = {".zip", ".safe"}
PREVIEW_KEY_HINTS = (
    "thumbnail",
    "preview",
    "quicklook",
    "browse",
    "overview",
    "rendered_preview",
)
S1_PRIORITY_HINTS = ("vv", "sigma0_vv", "gamma0_vv", "rtc", "vh", "sigma0_vh")
S2_PRIORITY_HINTS = ("b08", "b04", "b03", "b02", "visual", "true_color")
GENERIC_PRIORITY_HINTS = ("cog", "geotiff", "tif", "data", "analytic", "asset")
TIFF_MEDIA_HINTS = ("image/tiff", "geotiff", "cloud-optimized")


@dataclass(frozen=True)
class AssetProbe:
    ok: bool
    status: int | None
    content_type: str | None
    bytes_checked: int
    range_supported: bool | None


@dataclass(frozen=True)
class MaterializedScene:
    token: str
    scene: Scene
    provider: str
    sensor: str
    work_dir: Path
    raster_key: str
    raster_href: str
    raster_asset: SceneAsset
    raster_path: Path
    aoi_geojson: dict[str, object] | None = None
    cropped: bool = False
    cache_hit: bool = False
    asset_probe: AssetProbe | None = None


class MaterializationError(RuntimeError):
    pass


def materialize_scene_from_token(
    token: str,
    output_dir: Path,
    *,
    owner_user_id: int,
    owner_chat_id: int,
    cache_dir: Path | None = None,
) -> MaterializedScene:
    found = find_scene(
        output_dir,
        token,
        owner_user_id=owner_user_id,
        owner_chat_id=owner_chat_id,
    )
    if found is None:
        raise MaterializationError(f"Scene token not found or not owned by caller: {token}")
    scene, record = found
    selected = select_processing_asset_record(scene)
    if selected is None:
        keys = ", ".join(sorted(scene.assets)) or "no assets"
        raise MaterializationError(
            "No processable GeoTIFF/COG asset found for scene. "
            "Preview, XML and archive assets are not used for detection. "
            f"Available assets: {keys}"
        )
    raster_key, raster_asset, raster_href = selected
    provider = str(record.get("provider") or scene.provider)
    aoi_geojson = record.get("aoi_geojson") if isinstance(record.get("aoi_geojson"), dict) else None
    access_href, headers = prepare_asset_access(raster_href, provider, raster_asset)
    suffix = suffix_from_asset(raster_asset, raster_href)
    if cache_dir is None:
        target_path = raster_cache_path(
            provider=provider,
            product_id=scene.product_id,
            asset_key=raster_key,
            href=raster_href,
            aoi_geojson=aoi_geojson,
            suffix=suffix,
        )
        work_dir = target_path.parent
    else:
        work_dir = cache_dir / token
        target_path = work_dir / f"{safe_filename(raster_key)}_{short_hash(raster_href)}{suffix}"
    raster_path, cropped, cache_hit, probe = materialize_asset(
        access_href,
        target_path,
        aoi_geojson,
        headers=headers,
    )
    return MaterializedScene(
        token=token,
        scene=scene,
        provider=provider,
        sensor=str(record.get("sensor") or scene.sensor.value),
        work_dir=work_dir,
        raster_key=raster_key,
        raster_href=raster_href,
        raster_asset=raster_asset,
        raster_path=raster_path,
        aoi_geojson=aoi_geojson,
        cropped=cropped,
        cache_hit=cache_hit,
        asset_probe=probe,
    )


def select_processing_asset(scene: Scene) -> tuple[str, str] | None:
    """Compatibility wrapper returning key/href for search capability checks."""

    selected = select_processing_asset_record(scene)
    if selected is None:
        return None
    key, _asset, href = selected
    return key, href


def select_processing_asset_record(scene: Scene) -> tuple[str, SceneAsset, str] | None:
    candidates: list[tuple[str, SceneAsset, str]] = []
    for key in scene.assets:
        asset = scene.asset_record(key)
        if asset is None or is_preview_asset(key, asset) or not is_raster_asset(asset):
            continue
        href = asset.preferred_href(prefer_https=scene.provider == "copernicus_cdse")
        candidates.append((key, asset, href))
    if not candidates:
        return None
    priority = asset_priority_hints(scene)
    return sorted(
        candidates,
        key=lambda item: asset_score(item[0], item[1], item[2], priority, scene.provider),
    )[0]


def asset_priority_hints(scene: Scene) -> tuple[str, ...]:
    if scene.sensor.value == "sentinel1":
        return S1_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    if scene.sensor.value == "sentinel2":
        return S2_PRIORITY_HINTS + GENERIC_PRIORITY_HINTS
    return GENERIC_PRIORITY_HINTS


def asset_score(
    key: str,
    asset: SceneAsset,
    href: str,
    priority: tuple[str, ...],
    provider: str = "",
) -> tuple[int, int, int, int, str]:
    haystack = " ".join(
        [
            key,
            href,
            asset.media_type or "",
            asset.band or "",
            asset.polarization or "",
            " ".join(asset.roles),
        ]
    ).lower()
    semantic = next((index for index, hint in enumerate(priority) if hint in haystack), len(priority))
    role_penalty = 0 if any(role.lower() in {"data", "analytic", "backscatter"} for role in asset.roles) else 1
    media_penalty = 0 if is_tiff_media(asset.media_type) else 1
    storage_penalty = 0
    if provider == "copernicus_cdse" and href.lower().startswith("s3://"):
        storage_penalty = 3
    return semantic, role_penalty, media_penalty, storage_penalty, key


def is_preview_asset(key: str, asset: SceneAsset) -> bool:
    lowered = key.lower()
    roles = {role.lower() for role in asset.roles}
    return any(hint in lowered for hint in PREVIEW_KEY_HINTS) or bool(
        roles & {"thumbnail", "overview", "preview"}
    )


def is_raster_asset(asset: SceneAsset) -> bool:
    if is_tiff_media(asset.media_type):
        return True
    return any(suffix_from_href(href) in RASTER_EXTENSIONS for _name, href in asset.all_hrefs())


def is_tiff_media(media_type: str | None) -> bool:
    lowered = (media_type or "").lower()
    return any(hint in lowered for hint in TIFF_MEDIA_HINTS)


def prepare_asset_access(
    href: str,
    provider: str,
    asset: SceneAsset,
) -> tuple[str, dict[str, str]]:
    if provider == "planetary_computer" or asset.auth_mode == "runtime_signing":
        return sign_href_if_needed(href, "planetary_computer"), {}
    if provider == "copernicus_cdse" or asset.auth_mode == "bearer":
        token = cdse_access_token() if provider == "copernicus_cdse" else sentinelhub_access_token()
        if token:
            return href, bearer_headers(token)
        if asset.auth_mode == "bearer":
            raise MaterializationError(
                f"Bearer credentials are required for provider={provider}; configure its OAuth client"
            )
    if provider == "sentinelhub":
        token = sentinelhub_access_token()
        if token:
            return href, bearer_headers(token)
    return href, {}


def sign_href_if_needed(href: str, provider: str) -> str:
    if provider != "planetary_computer":
        return href
    try:
        import planetary_computer
    except ImportError:
        return href
    return str(planetary_computer.sign_url(href))


def materialize_asset(
    href: str,
    target: Path,
    aoi_geojson: dict[str, object] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[Path, bool, bool, AssetProbe]:
    suffix = suffix_from_href(href)
    if suffix in ARCHIVE_EXTENSIONS:
        raise MaterializationError(f"Archive assets are not supported yet: {safe_url(href)}")
    if suffix not in RASTER_EXTENSIONS and not href.startswith(("http://", "https://")):
        raise MaterializationError(f"Asset is not a GeoTIFF/COG: {safe_url(href)}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 0:
        probe = probe_raster_asset(str(target))
        touch_cache_file(target)
        return target, aoi_geojson is not None, True, probe

    probe = probe_raster_asset(href, headers=headers)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    if aoi_geojson is not None:
        crop_raster_to_aoi(href, tmp, aoi_geojson, headers=headers)
        tmp.replace(target)
        return target, True, False, probe
    if href.startswith(("http://", "https://")):
        download_url(href, tmp, headers=headers)
        tmp.replace(target)
        return target, False, False, probe
    source = Path(href)
    if source.is_file():
        tmp.write_bytes(source.read_bytes())
        tmp.replace(target)
        return target, False, False, probe
    raise MaterializationError(f"Asset path is not readable: {safe_url(href)}")


def probe_raster_asset(
    href: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
    max_bytes: int | None = None,
) -> AssetProbe:
    timeout = timeout or int(os.getenv("MARINE_TRACK_ASSET_PROBE_TIMEOUT_S", "30"))
    max_bytes = max_bytes or int(os.getenv("MARINE_TRACK_ASSET_PROBE_BYTES", "4096"))
    if href.startswith(("http://", "https://")):
        request_headers = {
            "User-Agent": "marine-track-asset-probe/0.1",
            "Range": f"bytes=0-{max_bytes - 1}",
            **(headers or {}),
        }
        request = Request(href, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                payload = response.read(max_bytes)
                status = getattr(response, "status", None) or response.getcode()
                content_type = response.headers.get("Content-Type") if response.headers else None
                accept_ranges = response.headers.get("Accept-Ranges") if response.headers else None
        except HTTPError as exc:
            raise MaterializationError(
                f"Raster access probe failed with HTTP {exc.code}: {safe_url(href)}"
            ) from exc
        except (OSError, URLError) as exc:
            raise MaterializationError(
                f"Raster access probe failed ({type(exc).__name__}): {safe_url(href)}"
            ) from exc
        if status not in {200, 206, None}:
            raise MaterializationError(f"Unexpected raster probe status {status}: {safe_url(href)}")
        if not _looks_like_tiff(payload, content_type):
            raise MaterializationError(
                f"Raster probe did not return TIFF bytes/content-type: {safe_url(href)}"
            )
        return AssetProbe(
            ok=True,
            status=status,
            content_type=content_type,
            bytes_checked=len(payload),
            range_supported=status == 206 or (accept_ranges or "").lower() == "bytes",
        )

    source = Path(href)
    if not source.is_file():
        raise MaterializationError(f"Local raster does not exist: {source}")
    payload = source.read_bytes()[:max_bytes]
    if not _looks_like_tiff(payload, None):
        raise MaterializationError(f"Local asset is not a TIFF raster: {source.name}")
    return AssetProbe(True, None, None, len(payload), None)


def crop_raster_to_aoi(
    href: str,
    target: Path,
    aoi_geojson: dict[str, object],
    *,
    headers: dict[str, str] | None = None,
) -> None:
    try:
        import rasterio
        from rasterio.mask import mask
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MaterializationError("rasterio is required for AOI crop") from exc

    header_value = _gdal_header_value(headers)
    context = rasterio.Env(GDAL_HTTP_HEADERS=header_value) if header_value else nullcontext()
    try:
        with context, rasterio.open(href) as dataset:
            geometries = extract_geometries(aoi_geojson, target_crs=dataset.crs)
            if not geometries:
                raise MaterializationError("AOI GeoJSON does not contain geometries")
            data, transform = mask(dataset, geometries, crop=True, filled=True)
            profile = dataset.profile.copy()
            profile.update(
                driver="GTiff",
                height=data.shape[1],
                width=data.shape[2],
                transform=transform,
                count=data.shape[0],
                compress="deflate",
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            profile.pop("tiled", None)
            with rasterio.open(target, "w", **profile) as output:
                output.write(data)
    except MaterializationError:
        raise
    except Exception as exc:
        raise MaterializationError(f"Failed to crop raster to AOI: {type(exc).__name__}") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise MaterializationError("AOI crop produced empty raster")


def extract_geometries(
    aoi_geojson: dict[str, object],
    target_crs: object | None = None,
) -> list[dict[str, object]]:
    geometries = raw_geometries(aoi_geojson)
    if not geometries:
        return []
    return transform_geometries_to_crs(geometries, target_crs)


def raw_geometries(aoi_geojson: dict[str, object]) -> list[dict[str, object]]:
    geo_type = aoi_geojson.get("type")
    if geo_type == "FeatureCollection":
        features = aoi_geojson.get("features") or []
        return [
            feature["geometry"]
            for feature in features
            if isinstance(feature, dict) and feature.get("geometry")
        ]
    if geo_type == "Feature":
        geometry = aoi_geojson.get("geometry")
        return [geometry] if isinstance(geometry, dict) else []
    if isinstance(geo_type, str):
        return [aoi_geojson]
    return []


def transform_geometries_to_crs(
    geometries: list[dict[str, object]],
    target_crs: object | None,
) -> list[dict[str, object]]:
    if target_crs is None:
        return geometries
    try:
        from pyproj import CRS, Transformer
        from shapely.geometry import mapping, shape
        from shapely.ops import transform
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MaterializationError("pyproj and shapely are required for AOI reprojection") from exc

    dst_crs = CRS.from_user_input(target_crs)
    if dst_crs.to_epsg() == 4326:
        return geometries
    transformer = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    return [mapping(transform(transformer.transform, shape(geometry))) for geometry in geometries]


def download_url(
    url: str,
    target: Path,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    request = Request(
        url,
        headers={"User-Agent": "marine-track-detect/0.1", **(headers or {})},
    )
    try:
        with urlopen(request, timeout=300) as response, target.open("wb") as file_obj:  # noqa: S310
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                file_obj.write(chunk)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise MaterializationError(
            f"Failed to download raster ({type(exc).__name__}): {safe_url(url)}"
        ) from exc
    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise MaterializationError(f"Downloaded empty asset: {safe_url(url)}")


def suffix_from_asset(asset: SceneAsset, href: str) -> str:
    suffix = suffix_from_href(href)
    if suffix in RASTER_EXTENSIONS:
        return suffix
    if is_tiff_media(asset.media_type):
        return ".tif"
    return suffix or ".tif"


def suffix_from_href(href: str) -> str:
    parsed = urlparse(href)
    return Path(parsed.path).suffix.lower()


def is_preview_key(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in PREVIEW_KEY_HINTS)


def is_raster_href(href: str) -> bool:
    return suffix_from_href(href) in RASTER_EXTENSIONS


def _looks_like_tiff(payload: bytes, content_type: str | None) -> bool:
    magic = payload[:4]
    if magic in {b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"}:
        return True
    return is_tiff_media(content_type)


def _gdal_header_value(headers: dict[str, str] | None) -> str | None:
    if not headers:
        return None
    return "\r\n".join(f"{key}: {value}" for key, value in headers.items())


def safe_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        return f"{parsed.scheme}://{parsed.hostname or ''}{parsed.path}"
    return value


def safe_filename(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned[:80] or "asset"


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
''',
)


write(
    "src/marine_track/assets.py",
    '''from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from marine_track.models import Scene

ASSET_MANIFEST_FIELDS = [
    "scene_id",
    "provider",
    "sensor",
    "acquisition_time",
    "asset_key",
    "href",
    "media_type",
    "roles",
    "band",
    "polarization",
    "units",
    "auth_mode",
    "storage",
    "alternate_hrefs",
    "local_path",
]


@dataclass(frozen=True)
class AssetRecord:
    scene_id: str
    provider: str
    sensor: str
    acquisition_time: str
    asset_key: str
    href: str
    media_type: str | None = None
    roles: str = ""
    band: str | None = None
    polarization: str | None = None
    units: str | None = None
    auth_mode: str = "unknown"
    storage: str = "unknown"
    alternate_hrefs: str = "{}"
    local_path: str | None = None


def safe_filename(value: str, max_len: int = 120) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:max_len - 11]}_{digest}"


def extension_from_href(href: str, default: str = ".bin") -> str:
    parsed = urlparse(href)
    name = Path(parsed.path).name
    suffixes = "".join(Path(name).suffixes)
    return suffixes or default


def iter_asset_records(scenes: list[Scene]) -> list[AssetRecord]:
    records: list[AssetRecord] = []
    for scene in scenes:
        keys = list(scene.assets)
        if not keys and scene.download_url:
            keys = ["product"]
        for key in keys:
            asset = scene.asset_record(key)
            href = asset.href if asset is not None else scene.download_url
            if not href:
                continue
            records.append(
                AssetRecord(
                    scene_id=scene.product_id,
                    provider=scene.provider,
                    sensor=scene.sensor.value,
                    acquisition_time=scene.acquisition_time.isoformat(),
                    asset_key=key,
                    href=sanitize_url(href),
                    media_type=asset.media_type if asset else None,
                    roles=",".join(asset.roles) if asset else "",
                    band=asset.band if asset else None,
                    polarization=asset.polarization if asset else None,
                    units=asset.units if asset else None,
                    auth_mode=asset.auth_mode if asset else "unknown",
                    storage=asset.storage if asset else "unknown",
                    alternate_hrefs=json.dumps(
                        {name: sanitize_url(value) for name, value in (asset.alternate_hrefs if asset else {}).items()},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                )
            )
    return records


def write_asset_manifest(scenes: list[Scene], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=ASSET_MANIFEST_FIELDS)
        writer.writeheader()
        for record in iter_asset_records(scenes):
            writer.writerow(record.__dict__)
    return output


def write_scenes_json(scenes: list[Scene], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = [scene.model_dump(mode="json") for scene in scenes]
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output)
    return output


def planned_asset_path(record: AssetRecord, cache_dir: str | Path) -> Path:
    scene_dir = Path(cache_dir) / safe_filename(record.scene_id)
    return scene_dir / f"{safe_filename(record.asset_key)}{extension_from_href(record.href)}"


def download_asset(record: AssetRecord, cache_dir: str | Path, overwrite: bool = False) -> Path:
    target = planned_asset_path(record, cache_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target
    request = Request(record.href, headers={"User-Agent": "marine-track-mvp/0.1"})
    with urlopen(request, timeout=120) as response, target.open("wb") as file_obj:  # noqa: S310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            file_obj.write(chunk)
    return target


def sanitize_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https", "s3", "az", "azure", "gs"}:
        return value
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit((parsed.scheme, hostname + port, parsed.path, "", ""))
''',
)


write(
    "docs/TYPED_ASSETS_CDSE.md",
    '''# Typed assets and CDSE materialization

`Scene.asset_records` is the canonical provider/materializer contract. The legacy
`Scene.assets: {key: href}` mapping remains serialized and readable for existing
registries and Telegram UI, while every legacy string is automatically promoted
to a `SceneAsset` at model validation time.

A typed asset records media type, roles, band/polarization, units, nodata,
scale/offset, storage/auth mode, alternate HTTPS/S3 references and sidecars.
Secrets are never stored in the scene or report. OAuth bearer headers and
Planetary Computer signatures are resolved immediately before probe/download.

The default CDSE STAC endpoint is `https://stac.dataspace.copernicus.eu/v1/`
with `sentinel-1-grd` and `sentinel-2-l2a`. Environment variables may override
all three values. For CDSE assets the materializer prefers an HTTPS alternate
over S3, obtains a transient OIDC token and sends it for the range-read canary,
GDAL/rasterio crop and download.

Before a remote asset reaches detection, the materializer requests the first
bytes with `Range: bytes=0-N` and verifies TIFF magic or TIFF media type. HTTP
401/403, non-raster responses and inaccessible storage fail before the expensive
detection stage. Configure probe limits with:

```dotenv
MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30
MARINE_TRACK_ASSET_PROBE_BYTES=4096
```

The asset manifest and reproducibility report contain only sanitized URLs and
typed domain metadata; bearer values and signed query strings are not persisted.
''',
)


write(
    "tests/test_typed_assets_cdse.py",
    '''from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from marine_track.data_sources.stac_provider import STACProvider, default_stac_providers
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.scene_materializer import (
    MaterializationError,
    prepare_asset_access,
    probe_raster_asset,
    select_processing_asset,
    select_processing_asset_record,
)


class FakeAsset:
    def __init__(self, href, media_type=None, roles=None, title=None, extra_fields=None):
        self.href = href
        self.media_type = media_type
        self.roles = roles
        self.title = title
        self.extra_fields = extra_fields or {}


class FakeItem:
    id = "S1_TEST"
    datetime = datetime(2026, 7, 10, tzinfo=timezone.utc)
    collection_id = "sentinel-1-grd"
    properties = {
        "datetime": "2026-07-10T00:00:00Z",
        "sar:polarizations": ["VV", "VH"],
    }
    links = []
    assets = {
        "vv": FakeAsset(
            "s3://eodata/path/vv.tif",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
            extra_fields={
                "raster:bands": [{"unit": "amplitude", "nodata": 0, "scale": 1.0}],
                "alternate": {"https": {"href": "https://download.example/vv.tif?token=secret"}},
            },
        ),
        "thumbnail": FakeAsset(
            "https://example/preview.jpg",
            media_type="image/jpeg",
            roles=["thumbnail"],
        ),
    }


def test_legacy_asset_mapping_is_promoted_to_typed_contract():
    scene = Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="legacy",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": "/tmp/a.tif"},
    )
    assert scene.assets["vv"] == "/tmp/a.tif"
    assert scene.asset_records["vv"].href == "/tmp/a.tif"
    assert scene.asset_records["vv"].storage == "local"


def test_stac_provider_preserves_typed_asset_metadata_and_https_alternate():
    provider = STACProvider(
        "copernicus_cdse",
        "https://stac.dataspace.copernicus.eu/v1/",
        {Sensor.SENTINEL1: ["sentinel-1-grd"]},
    )
    scene = provider._item_to_scene(FakeItem(), Sensor.SENTINEL1)
    record = scene.asset_records["vv"]
    assert record.media_type.startswith("image/tiff")
    assert record.roles == ["data"]
    assert record.polarization == "VV"
    assert record.units == "amplitude"
    assert record.nodata == 0
    assert record.alternate_hrefs["https"].startswith("https://")
    selected = select_processing_asset_record(scene)
    assert selected is not None
    assert selected[0] == "vv"
    assert selected[2].startswith("https://download.example/")
    assert select_processing_asset(scene)[1].startswith("https://download.example/")


def test_current_cdse_defaults_and_collection_overrides(monkeypatch):
    monkeypatch.delenv("CDSE_STAC_URL", raising=False)
    monkeypatch.delenv("CDSE_STAC_SENTINEL1_COLLECTION", raising=False)
    monkeypatch.delenv("CDSE_STAC_SENTINEL2_COLLECTION", raising=False)
    cdse = default_stac_providers()[0]
    assert cdse.api_url == "https://stac.dataspace.copernicus.eu/v1/"
    assert cdse.collections[Sensor.SENTINEL1] == ["sentinel-1-grd"]
    assert cdse.collections[Sensor.SENTINEL2] == ["sentinel-2-l2a"]


def test_cdse_bearer_is_transient(monkeypatch):
    asset = SceneAsset(
        href="https://download.example/a.tif",
        media_type="image/tiff",
        roles=["data"],
        auth_mode="bearer",
    )
    monkeypatch.setattr("marine_track.scene_materializer.cdse_access_token", lambda: "secret-token")
    href, headers = prepare_asset_access(asset.href, "copernicus_cdse", asset)
    assert href == asset.href
    assert headers == {"Authorization": "Bearer secret-token"}
    assert "secret-token" not in asset.model_dump_json()


def test_local_range_probe_checks_tiff_magic(tmp_path):
    path = tmp_path / "a.tif"
    path.write_bytes(b"II*\\x00" + b"x" * 64)
    probe = probe_raster_asset(str(path))
    assert probe.ok is True
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not-a-tiff")
    with pytest.raises(MaterializationError, match="not a TIFF"):
        probe_raster_asset(str(bad))


def test_remote_probe_sends_range_and_auth(monkeypatch):
    captured = {}

    class Response:
        status = 206
        headers = {"Content-Type": "image/tiff", "Accept-Ranges": "bytes"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"II*\\x00" + b"x" * max(0, size - 4)

        def getcode(self):
            return self.status

    def fake_urlopen(request, timeout):
        captured["range"] = request.headers.get("Range")
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("marine_track.scene_materializer.urlopen", fake_urlopen)
    probe = probe_raster_asset(
        "https://download.example/a.tif",
        headers={"Authorization": "Bearer token"},
        timeout=7,
        max_bytes=32,
    )
    assert probe.range_supported is True
    assert captured == {
        "range": "bytes=0-31",
        "authorization": "Bearer token",
        "timeout": 7,
    }


def test_preview_and_xml_sidecars_are_not_selected():
    scene = Scene(
        provider="copernicus_cdse",
        sensor=Sensor.SENTINEL1,
        product_id="x",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        asset_records={
            "thumbnail": SceneAsset(href="https://x/thumb.jpg", roles=["thumbnail"]),
            "calibration": SceneAsset(href="https://x/calibration.xml", roles=["metadata"]),
            "vv": SceneAsset(
                href="https://x/vv.tif",
                media_type="image/tiff",
                roles=["data"],
                polarization="VV",
            ),
        },
    )
    assert select_processing_asset(scene) == ("vv", "https://x/vv.tif")
''',
)


# Keep runtime examples aligned with the probe contract.
env_path = ROOT / ".env.example"
env_text = env_path.read_text(encoding="utf-8")
marker = "MARINE_TRACK_CODE_VERSION=\n"
addition = (
    "MARINE_TRACK_CODE_VERSION=\n"
    "# Remote GeoTIFF/COG range-read canary before materialization.\n"
    "MARINE_TRACK_ASSET_PROBE_TIMEOUT_S=30\n"
    "MARINE_TRACK_ASSET_PROBE_BYTES=4096\n"
)
if marker in env_text and "MARINE_TRACK_ASSET_PROBE_TIMEOUT_S" not in env_text:
    env_path.write_text(env_text.replace(marker, addition, 1), encoding="utf-8")

# Make typed domain visible in redacted reproducibility reports.
prov_path = ROOT / "src/marine_track/provenance.py"
prov = prov_path.read_text(encoding="utf-8")
old = '''    raster_key = str(materialized.raster_key)\n    suffix = Path(str(materialized.raster_href).split("?", 1)[0]).suffix.lower()\n    media_type = "image/tiff; application=geotiff" if suffix in {".tif", ".tiff"} else None\n    units = _first_present(metadata, "units", "unit", "radiometric_units", "measurement_units")\n    collection = _first_present(metadata, "collection", "collection_id", "stac_collection")\n    processing_level = _first_present(metadata, "processing_level", "product_type", "level")\n    return {\n        "collection": collection,\n        "processing_level": processing_level,\n        "asset_key": raster_key,\n        "media_type": media_type,\n        "units": units,\n        "polarizations": list(scene.polarizations or []),\n        "band_or_polarization": raster_key,\n        "href": sanitize_url(str(materialized.raster_href)),\n        "auth_mode": _auth_mode(materialized.provider, str(materialized.raster_href)),\n    }\n'''
new = '''    raster_key = str(materialized.raster_key)\n    suffix = Path(str(materialized.raster_href).split("?", 1)[0]).suffix.lower()\n    asset = getattr(materialized, "raster_asset", None) or scene.asset_record(raster_key)\n    media_type = (\n        asset.media_type\n        if asset is not None and asset.media_type\n        else "image/tiff; application=geotiff" if suffix in {".tif", ".tiff"} else None\n    )\n    units = (\n        asset.units\n        if asset is not None and asset.units\n        else _first_present(metadata, "units", "unit", "radiometric_units", "measurement_units")\n    )\n    collection = _first_present(metadata, "collection", "collection_id", "stac_collection")\n    processing_level = _first_present(metadata, "processing_level", "product_type", "level")\n    return {\n        "collection": collection,\n        "processing_level": processing_level,\n        "asset_key": raster_key,\n        "media_type": media_type,\n        "roles": list(asset.roles) if asset is not None else [],\n        "band": asset.band if asset is not None else None,\n        "polarization": asset.polarization if asset is not None else None,\n        "units": units,\n        "nodata": asset.nodata if asset is not None else None,\n        "scale": asset.scale if asset is not None else None,\n        "offset": asset.offset if asset is not None else None,\n        "storage": asset.storage if asset is not None else "unknown",\n        "polarizations": list(scene.polarizations or []),\n        "band_or_polarization": (\n            asset.band or asset.polarization if asset is not None else raster_key\n        ),\n        "href": sanitize_url(str(materialized.raster_href)),\n        "alternate_hrefs": {\n            key: sanitize_url(value) for key, value in (asset.alternate_hrefs if asset else {}).items()\n        },\n        "sidecar_keys": sorted((asset.sidecars if asset else {}).keys()),\n        "auth_mode": asset.auth_mode if asset is not None else _auth_mode(\n            materialized.provider, str(materialized.raster_href)\n        ),\n    }\n'''
if old not in prov:
    raise RuntimeError("provenance asset-domain block not found")
prov_path.write_text(prov.replace(old, new, 1), encoding="utf-8")

print("typed asset/CDSE migration applied")
