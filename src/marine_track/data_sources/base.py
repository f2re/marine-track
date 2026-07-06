from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from marine_track.models import Scene, Sensor


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class SearchRequest:
    aoi_geojson_path: Path
    start: datetime
    end: datetime
    sensor: Sensor
    max_results: int = 50


class SceneProvider(ABC):
    name: str
    supported_sensors: set[Sensor]

    def can_handle(self, sensor: Sensor) -> bool:
        return sensor in self.supported_sensors

    @abstractmethod
    def search(self, request: SearchRequest) -> list[Scene]:
        raise NotImplementedError


class SourceManager:
    def __init__(self, providers: Iterable[SceneProvider]):
        self.providers = list(providers)

    def search_first_available(
        self,
        request: SearchRequest,
        provider_order: list[str] | None = None,
    ) -> tuple[str, list[Scene]]:
        ordered = self.providers
        if provider_order:
            index = {name: i for i, name in enumerate(provider_order)}
            ordered = sorted(self.providers, key=lambda p: index.get(p.name, len(index)))

        errors: list[str] = []
        for provider in ordered:
            if not provider.can_handle(request.sensor):
                continue
            try:
                scenes = provider.search(request)
            except Exception as exc:  # noqa: BLE001 - fallback must survive provider failures
                errors.append(f"{provider.name}: {exc}")
                continue
            if scenes:
                return provider.name, scenes

        details = "; ".join(errors) if errors else "no provider returned scenes"
        raise ProviderError(f"No scenes found for {request.sensor}. Details: {details}")
