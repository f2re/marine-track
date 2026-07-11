from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from marine_track.assets import write_asset_manifest, write_scenes_json
from marine_track.cache_policy import (
    read_scene_search_cache,
    search_cache_key,
    search_cache_path,
    write_scene_search_cache,
)
from marine_track.data_sources import SearchRequest, SentinelHubProvider, default_stac_providers
from marine_track.models import Scene, Sensor
from marine_track.resource_limits import validate_aoi_path
from marine_track.scene_materializer import select_processing_asset
from marine_track.sensor_preprocessing import (
    SensorPreprocessingError,
    ensure_detection_sensor_supported,
)

DETECTION_PROVIDER_ORDER = {
    Sensor.SENTINEL1: ["planetary_computer", "copernicus_cdse", "sentinelhub"],
    Sensor.SENTINEL2: ["planetary_computer", "earthsearch", "copernicus_cdse", "sentinelhub"],
}


@dataclass(frozen=True)
class DetectionSceneSearchResult:
    provider: str
    sensor: Sensor
    scenes: list[Scene]
    scenes_json: Path
    asset_manifest: Path
    cache_hit: bool = False


def search_detection_capable_scenes(
    aoi: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    output: Path,
    max_results: int = 20,
) -> DetectionSceneSearchResult:
    validate_aoi_path(aoi)
    if sensor != Sensor.AUTO:
        ensure_detection_sensor_supported(sensor)
    output.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    cache_key = search_cache_key(
        aoi,
        start,
        end,
        sensor,
        max_results,
        purpose="detection",
        capability="processable_geotiff_cog",
    )
    cached = read_scene_search_cache(search_cache_path(cache_key))
    if cached is not None:
        provider, concrete_sensor, scenes = cached
        processable = _processable_sorted(scenes)
        if processable:
            try:
                ensure_detection_sensor_supported(concrete_sensor)
            except SensorPreprocessingError as exc:
                errors.append(f"{concrete_sensor.value}/cache: {exc}")
            else:
                scenes_json = write_scenes_json(processable, output / "scenes.json")
                asset_manifest = write_asset_manifest(processable, output / "assets.csv")
                return DetectionSceneSearchResult(
                    provider=provider,
                    sensor=concrete_sensor,
                    scenes=processable,
                    scenes_json=scenes_json,
                    asset_manifest=asset_manifest,
                    cache_hit=True,
                )

    providers = {
        provider.name: provider
        for provider in [*default_stac_providers(), SentinelHubProvider()]
    }

    for concrete_sensor in resolve_sensor_order(sensor):
        try:
            ensure_detection_sensor_supported(concrete_sensor)
        except SensorPreprocessingError as exc:
            errors.append(f"{concrete_sensor.value}: {exc}")
            continue
        request = SearchRequest(
            aoi_geojson_path=aoi,
            start=start,
            end=end,
            sensor=concrete_sensor,
            max_results=max_results,
        )
        for provider_name in DETECTION_PROVIDER_ORDER.get(concrete_sensor, []):
            provider = providers.get(provider_name)
            if provider is None or not provider.can_handle(concrete_sensor):
                continue
            try:
                scenes = provider.search(request)
                processable = _processable_sorted(scenes)
                if processable:
                    scenes_json = write_scenes_json(processable, output / "scenes.json")
                    asset_manifest = write_asset_manifest(processable, output / "assets.csv")
                    write_scene_search_cache(
                        search_cache_path(cache_key),
                        provider_name,
                        concrete_sensor,
                        processable,
                    )
                    return DetectionSceneSearchResult(
                        provider=provider_name,
                        sensor=concrete_sensor,
                        scenes=processable,
                        scenes_json=scenes_json,
                        asset_manifest=asset_manifest,
                        cache_hit=False,
                    )
                errors.append(
                    f"{concrete_sensor.value}/{provider_name}: no GeoTIFF/COG assets"
                )
            except Exception as exc:  # noqa: BLE001 - fallback must continue
                errors.append(f"{concrete_sensor.value}/{provider_name}: {exc}")
    raise RuntimeError("No detection-capable scenes found. " + "; ".join(errors))


def _processable_sorted(scenes: list[Scene]) -> list[Scene]:
    output = [scene for scene in scenes if select_processing_asset(scene) is not None]
    output.sort(
        key=lambda scene: (scene.acquisition_time, scene.product_id),
        reverse=True,
    )
    return output


def resolve_sensor_order(sensor: Sensor) -> list[Sensor]:
    if sensor == Sensor.AUTO:
        return [Sensor.SENTINEL1, Sensor.SENTINEL2]
    return [sensor]
