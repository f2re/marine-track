from __future__ import annotations

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
