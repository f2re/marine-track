from __future__ import annotations

import json

from marine_track.models import Sensor
from marine_track.telegram_config import load_telegram_config
from marine_track.telegram_detection import compact_default_detection_aoi


def _write_aoi(path) -> None:
    path.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [36.5, 43.8],
                        [38.5, 43.8],
                        [38.5, 45.0],
                        [36.5, 45.0],
                        [36.5, 43.8],
                    ]
                ],
            }
        ),
        encoding="utf-8",
    )


def test_default_menu_detection_sector_stays_below_detection_limit(tmp_path, monkeypatch) -> None:
    aoi = tmp_path / "default.geojson"
    _write_aoi(aoi)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "1")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_AOI", str(aoi))
    monkeypatch.delenv("MARINE_TRACK_DEFAULT_DETECTION_SIDE_KM", raising=False)

    config = load_telegram_config()
    compact = compact_default_detection_aoi(config)

    assert config.default_sensor == Sensor.AUTO
    assert config.default_detection_side_km == 16
    assert compact.area_km2 < 400.0


def test_default_detection_side_is_clamped_below_geodesic_ceiling(tmp_path, monkeypatch) -> None:
    aoi = tmp_path / "default.geojson"
    _write_aoi(aoi)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "1")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_AOI", str(aoi))
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_DETECTION_SIDE_KM", "99")

    config = load_telegram_config()
    compact = compact_default_detection_aoi(config)

    assert config.default_detection_side_km == 19
    assert compact.area_km2 < 400.0
