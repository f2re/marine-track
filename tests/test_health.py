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
    capabilities = next(item for item in report.checks if item.name == "sensor_capabilities")
    assert capabilities.status == "ok"
    assert capabilities.data["sentinel2_single_band_experimental"] is False
    user_state = next(item for item in report.checks if item.name == "telegram_user_state")
    assert user_state.status == "warning"
    assert user_state.data["users"] == 0
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


def test_health_report_exposes_release_identity(monkeypatch, tmp_path):
    base = tmp_path / "release"
    (base / "config").mkdir(parents=True)
    (base / "data" / "aoi").mkdir(parents=True)
    (base / "config" / "processing.yaml").write_text(
        "ship_detection:\n  sar:\n    threshold_sigma: 3.5\n    min_area_px: 2\n    max_area_px: 5000\n    local_window_px: 31\n    guard_window_px: 5\n  optical:\n    threshold_sigma: 3.5\n    min_area_px: 2\n    max_area_px: 3000\n    local_window_px: 31\n    guard_window_px: 5\n",
        encoding="utf-8",
    )
    (base / "data" / "aoi" / "example_black_sea.geojson").write_text(
        '{"type":"Polygon","coordinates":[[[30,43],[30.1,43],[30.1,43.1],[30,43.1],[30,43]]]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MARINE_TRACK_CODE_VERSION", "abc123")
    monkeypatch.setenv("MARINE_TRACK_RELEASE_ID", "abc123-20260710T120000Z")
    monkeypatch.setenv("MARINE_TRACK_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("MARINE_TRACK_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    report = collect_health(base_dir=base)
    assert report.code_version == "abc123"
    assert report.release_id == "abc123-20260710T120000Z"
    assert report.to_dict()["release_id"] == "abc123-20260710T120000Z"


def test_valid_transactional_user_state_has_separate_health_check(tmp_path, monkeypatch):
    from marine_track.telegram_user_state import OUTPUT_MODE_IMAGES, set_output_mode

    configure(tmp_path, monkeypatch)
    output_dir = tmp_path / "state" / "output"
    set_output_mode(output_dir, 77, OUTPUT_MODE_IMAGES)

    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "telegram_user_state")

    assert check.status == "ok"
    assert check.critical is False
    assert check.data == {
        "schema_version": 1,
        "users": 1,
        "quarantined": 0,
        "atomic_replace": True,
        "inter_process_lock": True,
    }


def test_legacy_user_state_is_a_noncritical_health_warning(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    output_dir = tmp_path / "state" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "telegram_user_state.json").write_text(
        '{"users":{"7":{"output_mode":"images"}}}\n',
        encoding="utf-8",
    )

    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "telegram_user_state")

    assert report.status == "degraded"
    assert check.status == "warning"
    assert check.critical is False
    assert check.data["schema_version"] == 0
    assert "legacy" in check.detail


def test_corrupt_user_state_is_critical_and_health_does_not_leak_path(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    output_dir = tmp_path / "state" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "telegram_user_state.json").write_text("{broken", encoding="utf-8")

    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "telegram_user_state")
    serialized = json.dumps(check.__dict__)

    assert report.status == "failed"
    assert check.status == "failed"
    assert check.critical is True
    assert "invalid JSON" in check.detail
    assert str(tmp_path) not in serialized


def test_unsupported_user_state_schema_is_critical_and_not_quarantined(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    output_dir = tmp_path / "state" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    state = output_dir / "telegram_user_state.json"
    state.write_text('{"schema_version":2,"users":{}}\n', encoding="utf-8")

    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "telegram_user_state")

    assert report.status == "failed"
    assert check.status == "failed"
    assert check.critical is True
    assert "unsupported schema_version 2" in check.detail
    assert list(output_dir.glob("telegram_user_state.corrupt-*.json")) == []
