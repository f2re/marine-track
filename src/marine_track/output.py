from __future__ import annotations

import json
from pathlib import Path

from marine_track.models import VesselDetection


def write_geojson(detections: list[VesselDetection], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "features": [d.to_geojson_feature() for d in detections],
    }
    p.write_text(json.dumps(fc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
