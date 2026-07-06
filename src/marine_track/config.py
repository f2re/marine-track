from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    sources: dict[str, Any] = Field(default_factory=dict)
    processing: dict[str, Any] = Field(default_factory=dict)


def load_yaml(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(
    sources_path: str | Path = "config/sources.yaml",
    processing_path: str | Path = "config/processing.yaml",
) -> AppConfig:
    return AppConfig(
        sources=load_yaml(sources_path),
        processing=load_yaml(processing_path),
    )
