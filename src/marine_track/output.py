from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from marine_track.models import VesselDetection


def detections_to_feature_collection(detections: list[VesselDetection]) -> dict[str, object]:
    return {
        "type": "FeatureCollection",
        "features": [d.to_geojson_feature() for d in detections],
    }


def write_geojson(detections: list[VesselDetection], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(detections_to_feature_collection(detections), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return p


def write_parquet(detections: list[VesselDetection], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [d.model_dump(mode="json") for d in detections]
    pd.DataFrame(rows).to_parquet(p, index=False)
    return p


def write_csv(detections: list[VesselDetection], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [d.model_dump(mode="json") for d in detections]
    pd.DataFrame(rows).to_csv(p, index=False)
    return p
