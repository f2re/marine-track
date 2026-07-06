from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from marine_track.assets import write_asset_manifest, write_scenes_json
from marine_track.data_sources import SearchRequest, SourceManager, default_stac_providers
from marine_track.models import Scene, Sensor
from marine_track.scene_materializer import select_processing_asset

DETECTION_PROVIDER_ORDER = {
    Sensor.SENTINEL1: ["planetary_computer", "copernicus_cdse"],
    Sensor.SENTINEL2: ["planetary_computer", "earthsearch", "copernicus_cdse"],
}


@dataclass(frozen=True)
class DetectionSceneSearchResult:
    provider: str
    sensor: Sensor
    scenes: list[Scene]
    scenes_json: Path
    asset_manifest: Path


def search_detection_capable_scenes(
    aoi: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    output: Path,
    max_results: int = 20,
) -> DetectionSceneSearchResult:
    output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    manager = SourceManager(default_stac_providers())

    for concrete_sensor in resolve_sensor_order(sensor):
        request = SearchRequest(
            aoi_geojson_path=aoi,
            start=start,
            end=end,
            sensor=concrete_sensor,
            max_results=max_results,
        )
        for provider_name in DETECTION_PROVIDER_ORDER.get(concrete_sensor, []):
            try:
                provider = manager.providers[provider_name]
                scenes = provider.search(request)
                processable = [scene for scene in scenes if select_processing_asset(scene) is not None]
                if processable:
                    scenes_json = write_scenes_json(processable, output / "scenes.json")
                    asset_manifest = write_asset_manifest(processable, output / "assets.csv")
                    return DetectionSceneSearchResult(
                        provider=provider_name,
                        sensor=concrete_sensor,
                        scenes=processable,
                        scenes_json=scenes_json,
                        asset_manifest=asset_manifest,
                    )
                errors.append(f"{concrete_sensor.value}/{provider_name}: no GeoTIFF/COG assets")
            except Exception as exc:  # noqa: BLE001 - fallback must continue
                errors.append(f"{concrete_sensor.value}/{provider_name}: {exc}")
    raise RuntimeError("No detection-capable scenes found. " + "; ".join(errors))


def resolve_sensor_order(sensor: Sensor) -> list[Sensor]:
    if sensor == Sensor.AUTO:
        return [Sensor.SENTINEL1, Sensor.SENTINEL2]
    return [sensor]
