from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Sensor(str, Enum):
    AUTO = "auto"
    SENTINEL1 = "sentinel1"
    SENTINEL2 = "sentinel2"


class SpeedMethod(str, Enum):
    NOT_ESTIMATED = "not_estimated"
    SENTINEL2_INTERBAND = "sentinel2_interband_displacement"
    KELVIN_WAVELENGTH = "kelvin_wavelength"
    SAR_OFFSET_EXPERIMENTAL = "sar_offset_experimental"


class HeadingMethod(str, Enum):
    NOT_ESTIMATED = "not_estimated"
    WAKE_AXIS = "wake_axis"
    HULL_ORIENTATION = "hull_orientation"
    SENTINEL2_INTERBAND = "sentinel2_interband_displacement"


class Scene(BaseModel):
    provider: str
    sensor: Sensor
    product_id: str
    acquisition_time: datetime
    footprint_wkt: str | None = None
    download_url: str | None = None
    assets: dict[str, str] = Field(default_factory=dict)
    cloud_cover: float | None = None
    polarizations: list[str] | None = None
    beam_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def polarization_label(self) -> str:
        if self.polarizations:
            return ",".join(self.polarizations)
        if self.cloud_cover is not None:
            return f"cloud={self.cloud_cover:.1f}"
        return "-"


class VesselDetection(BaseModel):
    detection_id: str
    lon: float
    lat: float
    satellite: str
    provider: str
    product_id: str
    acquisition_time: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    wake_type: str = "unknown"
    heading_deg: float | None = None
    heading_method: HeadingMethod = HeadingMethod.NOT_ESTIMATED
    heading_error_deg: float | None = None
    heading_ambiguity_deg: float | None = None
    speed_knots: float | None = None
    speed_method: SpeedMethod = SpeedMethod.NOT_ESTIMATED
    speed_reference: str | None = None
    validation_status: str = "unvalidated"
    validation: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_geojson_feature(self) -> dict[str, Any]:
        props = self.model_dump(mode="json")
        lon = props.pop("lon")
        lat = props.pop("lat")
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        }
