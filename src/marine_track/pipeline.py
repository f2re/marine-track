from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from marine_track.assets import write_asset_manifest, write_scenes_json
from marine_track.config import AppConfig, load_config
from marine_track.data_sources import (
    ASFProvider,
    SearchRequest,
    SentinelHubProvider,
    SourceManager,
    default_stac_providers,
)
from marine_track.models import Scene, Sensor


@dataclass(frozen=True)
class SearchStageResult:
    provider: str
    sensor: Sensor
    scene_count: int
    scenes_json: Path
    asset_manifest: Path | None


def parse_utc_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_source_manager() -> SourceManager:
    providers = [ASFProvider(), *default_stac_providers(), SentinelHubProvider()]
    return SourceManager(providers)


def resolve_sensor_order(sensor: Sensor) -> list[Sensor]:
    if sensor == Sensor.AUTO:
        return [Sensor.SENTINEL1, Sensor.SENTINEL2]
    return [sensor]


def provider_order_for_sensor(config: AppConfig, sensor: Sensor) -> list[str]:
    try:
        return list(config.sources["sensors"][sensor.value]["priority"])
    except KeyError:
        return []


def search_scenes_with_fallback(
    config: AppConfig,
    aoi: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    max_results: int = 50,
) -> tuple[str, Sensor, list[Scene]]:
    manager = build_source_manager()
    errors: list[str] = []

    for concrete_sensor in resolve_sensor_order(sensor):
        request = SearchRequest(
            aoi_geojson_path=aoi,
            start=start,
            end=end,
            sensor=concrete_sensor,
            max_results=max_results,
        )
        try:
            provider, scenes = manager.search_first_available(
                request,
                provider_order=provider_order_for_sensor(config, concrete_sensor),
            )
            return provider, concrete_sensor, scenes
        except Exception as exc:  # noqa: BLE001 - auto mode must try next sensor
            errors.append(f"{concrete_sensor.value}: {exc}")

    raise RuntimeError("No scenes found. " + "; ".join(errors))


def run_search_stage(
    aoi: Path,
    start: datetime,
    end: datetime,
    sensor: Sensor,
    output: Path,
    max_results: int = 50,
    write_manifest: bool = True,
) -> SearchStageResult:
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    provider, concrete_sensor, scenes = search_scenes_with_fallback(
        config=config,
        aoi=aoi,
        start=start,
        end=end,
        sensor=sensor,
        max_results=max_results,
    )
    scenes_json = write_scenes_json(scenes, output / "scenes.json")
    asset_manifest = write_asset_manifest(scenes, output / "assets.csv") if write_manifest else None
    return SearchStageResult(
        provider=provider,
        sensor=concrete_sensor,
        scene_count=len(scenes),
        scenes_json=scenes_json,
        asset_manifest=asset_manifest,
    )
