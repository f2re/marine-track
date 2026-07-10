from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from marine_track.models import Sensor


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    admin_ids: set[int]
    default_aoi: Path
    output_dir: Path
    default_sensor: Sensor
    default_lookback_hours: int
    max_results: int
    max_concurrent_jobs: int
    detection_max_crops: int
    land_mask_geojson: Path | None
    shoreline_buffer_m: int
    calibration_min_labels: int = 20
    calibration_min_positive: int = 5
    calibration_min_negative: int = 5
    calibration_crop_size_px: int = 768


def parse_admin_ids(raw: str | None) -> set[int]:
    ids: set[int] = set()
    if not raw:
        return ids
    for part in raw.replace(";", ",").replace(" ", ",").split(","):
        value = part.strip()
        if not value:
            continue
        try:
            ids.add(int(value))
        except ValueError:
            continue
    return ids


def env_int(name: str, default: int, minimum: int = 1, maximum: int = 10000) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def env_optional_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else None


def load_telegram_config() -> TelegramBotConfig:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty. Set it in .env before startup.")

    sensor_raw = os.getenv("MARINE_TRACK_DEFAULT_SENSOR", Sensor.AUTO.value).strip().lower()
    try:
        default_sensor = Sensor(sensor_raw)
    except ValueError:
        default_sensor = Sensor.AUTO

    calibration_min_labels = env_int("MARINE_TRACK_CALIBRATION_MIN_LABELS", 20, 4, 100000)
    calibration_min_positive = env_int("MARINE_TRACK_CALIBRATION_MIN_POSITIVE", 5, 1, calibration_min_labels)
    calibration_min_negative = env_int("MARINE_TRACK_CALIBRATION_MIN_NEGATIVE", 5, 1, calibration_min_labels)

    return TelegramBotConfig(
        token=token,
        admin_ids=parse_admin_ids(os.getenv("TELEGRAM_ADMIN_IDS")),
        default_aoi=Path(os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson")),
        output_dir=Path(os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram")),
        default_sensor=default_sensor,
        default_lookback_hours=env_int("MARINE_TRACK_DEFAULT_LOOKBACK_HOURS", 72, 1, 24 * 30),
        max_results=env_int("MARINE_TRACK_MAX_RESULTS", 10, 1, 100),
        max_concurrent_jobs=env_int("MARINE_TRACK_MAX_CONCURRENT_JOBS", 1, 1, 10),
        detection_max_crops=env_int("MARINE_TRACK_DETECTION_MAX_CROPS", 10, 0, 100),
        land_mask_geojson=env_optional_path("MARINE_TRACK_LAND_MASK_GEOJSON"),
        shoreline_buffer_m=env_int("MARINE_TRACK_SHORELINE_BUFFER_M", 500, 0, 100_000),
        calibration_min_labels=calibration_min_labels,
        calibration_min_positive=calibration_min_positive,
        calibration_min_negative=calibration_min_negative,
        calibration_crop_size_px=env_int("MARINE_TRACK_CALIBRATION_CROP_SIZE_PX", 768, 384, 1200),
    )
