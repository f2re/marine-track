from __future__ import annotations

import json
from pathlib import Path

from marine_track.health import collect_health


def write_processing(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """ship_detection:
  sar:
    threshold_sigma: 3.5
    min_area_px: 2
    max_area_px: 5000
    local_window_px: 31
    guard_window_px: 5
  optical:
    threshold_sigma: 3.5
    min_area_px: 2
    max_area_px: 3000
    local_window_px: 31
    guard_window_px: 5
""",
        encoding="utf-8",
    )


def configure(tmp_path, monkeypatch):
    write_processing(tmp_path / "config" / "processing.yaml")
    aoi = tmp_path / "data" / "aoi.geojson"
    aoi.parent.mkdir(parents=True)
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    monkeypatch.setenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi.geojson")
    monkeypatch.setenv("MARINE_TRACK_OUTPUT_DIR", "state/output")
    monkeypatch.setenv("MARINE_TRACK_CACHE_DIR", "state/cache")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "0")
    monkeypatch.setenv("MARINE_TRACK_HEALTH_MIN_FREE_MB", "1")


def test_health_is_degraded_but_non_failed_before_first_calibration(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    report = collect_health(base_dir=tmp_path)
    assert report.status == "degraded"
    assert not any(check.critical and check.status == "failed" for check in report.checks)
    serialized = json.dumps(report.to_dict())
    assert "TELEGRAM_BOT_TOKEN" not in serialized


def test_corrupt_registry_is_critical(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    registry = tmp_path / "state" / "output" / "scene_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{broken", encoding="utf-8")
    report = collect_health(base_dir=tmp_path)
    assert report.status == "failed"
    check = next(item for item in report.checks if item.name == "scene_registry")
    assert check.critical is True


def test_scoped_registry_is_accepted(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    registry = tmp_path / "state" / "output" / "scene_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"token": {"owner_user_id": 123, "owner_chat_id": 456}}),
        encoding="utf-8",
    )
    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "scene_registry")
    assert check.status == "ok"


def test_fail_closed_access_policy_is_health_failure(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "")
    report = collect_health(base_dir=tmp_path)
    assert report.status == "failed"
