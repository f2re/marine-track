from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import marine_track.provider_canary as canary
from marine_track.detection_scene_search import DetectionSceneSearchResult
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.scene_materializer import AssetProbe


def write_aoi(path: Path, west: float = 30.0, south: float = 43.0, east: float = 30.1, north: float = 43.1) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [west, south],
                        [east, south],
                        [east, north],
                        [west, north],
                        [west, south],
                    ]
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def fake_scene() -> Scene:
    asset = SceneAsset(
        href="https://example.test/data/scene.tif?sig=original-secret",
        media_type="image/tiff; application=geotiff",
        roles=["data", "backscatter"],
        polarization="VV",
        units="sigma0",
        auth_mode="runtime_signing",
        storage="https",
    )
    return Scene(
        provider="planetary_computer",
        sensor=Sensor.SENTINEL1,
        product_id="S1_TEST_PRODUCT",
        acquisition_time=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        assets={"vv": asset.href},
        asset_records={"vv": asset},
        polarizations=["VV"],
    )


def install_asset_mocks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    scene = fake_scene()
    scenes_json = tmp_path / "scenes.json"
    assets_csv = tmp_path / "assets.csv"
    scenes_json.write_text("[]\n", encoding="utf-8")
    assets_csv.write_text("key,href\n", encoding="utf-8")
    search_result = DetectionSceneSearchResult(
        provider="planetary_computer",
        sensor=Sensor.SENTINEL1,
        scenes=[scene],
        scenes_json=scenes_json,
        asset_manifest=assets_csv,
        cache_hit=False,
    )
    calls: dict[str, object] = {}

    def fake_search(*args, **kwargs):
        calls["search_args"] = args
        calls["search_kwargs"] = kwargs
        return search_result

    def fake_access(href, provider, asset):
        calls["access"] = (href, provider, asset)
        return (
            "https://example.test/data/scene.tif?sig=TOP-SECRET&token=PRIVATE",
            {"Authorization": "Bearer VERY-SECRET"},
        )

    def fake_probe(href, *, headers=None, **kwargs):
        calls["probe"] = (href, headers, kwargs)
        return AssetProbe(True, 206, "image/tiff", 4096, True)

    monkeypatch.setattr(canary, "search_detection_capable_scenes", fake_search)
    monkeypatch.setattr(canary, "prepare_asset_access", fake_access)
    monkeypatch.setattr(canary, "probe_raster_asset", fake_probe)
    calls["scene"] = scene
    calls["search_result"] = search_result
    return calls


def test_build_canary_aoi_derives_compact_sector_from_default(tmp_path):
    default = write_aoi(tmp_path / "default.geojson", 29.0, 42.0, 31.0, 44.0)

    result = canary.build_canary_aoi(
        base_dir=tmp_path,
        default_aoi=default.name,
        side_km=8.0,
        max_area_km2=100.0,
    )

    assert result.source == "derived_from_default_aoi"
    assert 1.0 < result.area_km2 <= 100.0
    assert result.vertex_count >= 4
    assert len(result.aoi_hash) == 64
    assert 29.0 <= result.bounds[0] < result.bounds[2] <= 31.0
    assert 42.0 <= result.bounds[1] < result.bounds[3] <= 44.0


def test_asset_canary_redacts_credentials_urls_and_local_paths(tmp_path, monkeypatch):
    explicit = write_aoi(tmp_path / "canary.geojson")
    calls = install_asset_mocks(monkeypatch, tmp_path)

    result = canary.run_provider_canary(
        mode="asset",
        output_dir=tmp_path / "output",
        default_aoi=explicit,
        explicit_aoi=explicit,
        base_dir=tmp_path,
        now=datetime(2026, 7, 11, 8, tzinfo=timezone.utc),
    )

    assert result.ok
    assert calls["probe"][1] == {"Authorization": "Bearer VERY-SECRET"}
    assert result.report["result"]["asset"]["access_mode"] == "transient_headers"
    assert result.report["result"]["asset"]["probe"]["range_supported"] is True
    serialized = result.report_path.read_text(encoding="utf-8")
    assert "TOP-SECRET" not in serialized
    assert "VERY-SECRET" not in serialized
    assert "original-secret" not in serialized
    assert str(tmp_path) not in serialized
    assert "?sig=" not in serialized
    assert stat.S_IMODE(result.report_path.stat().st_mode) == 0o600
    latest = canary.load_latest_canary_report(tmp_path / "output")
    assert latest and latest["canary_id"] == result.report["canary_id"]


def test_detection_canary_uses_scoped_registry_and_disables_wake(tmp_path, monkeypatch):
    explicit = write_aoi(tmp_path / "canary.geojson")
    calls = install_asset_mocks(monkeypatch, tmp_path)

    def fake_register(output_dir, provider, sensor, scenes, scenes_json, asset_manifest, **kwargs):
        calls["register"] = {
            "output_dir": output_dir,
            "provider": provider,
            "sensor": sensor,
            "scenes": scenes,
            "scenes_json": scenes_json,
            "asset_manifest": asset_manifest,
            **kwargs,
        }
        return ["scoped-canary-token"]

    def fake_detection(**kwargs):
        calls["detection"] = kwargs
        return SimpleNamespace(
            detections=[object(), object()],
            materialized=SimpleNamespace(cache_hit=False, cropped=True),
            preprocessing_plan=SimpleNamespace(
                output_domain="relative_db",
                calibration_status="relative_uncalibrated_amplitude",
            ),
            wake_research_enabled=False,
        )

    monkeypatch.setattr(canary, "register_scenes", fake_register)
    monkeypatch.setattr(canary, "run_detection_for_token", fake_detection)

    result = canary.run_provider_canary(
        mode=canary.CanaryMode.DETECTION,
        output_dir=tmp_path / "output",
        default_aoi=explicit,
        explicit_aoi=explicit,
        base_dir=tmp_path,
        owner_user_id=123,
        owner_chat_id=-456,
        now=datetime(2026, 7, 11, 8, tzinfo=timezone.utc),
    )

    assert result.ok
    assert calls["register"]["owner_user_id"] == 123
    assert calls["register"]["owner_chat_id"] == -456
    assert calls["detection"]["wake_research"] is False
    assert calls["detection"]["max_crops"] == 0
    assert result.report["result"]["detection"] == {
        "candidate_count": 2,
        "raster_cache_hit": False,
        "aoi_cropped": True,
        "preprocessing_domain": "relative_db",
        "calibration_status": "relative_uncalibrated_amplitude",
        "wake_research_enabled": False,
    }


def test_failed_canary_persists_sanitized_stage_and_error(tmp_path, monkeypatch):
    explicit = write_aoi(tmp_path / "canary.geojson")

    def fail_search(*args, **kwargs):
        del args, kwargs
        raise RuntimeError(
            "provider failed https://example.test/search?token=SECRET /srv/private/data password=HIDDEN"
        )

    monkeypatch.setattr(canary, "search_detection_capable_scenes", fail_search)
    result = canary.run_provider_canary(
        mode="asset",
        output_dir=tmp_path / "output",
        default_aoi=explicit,
        explicit_aoi=explicit,
        base_dir=tmp_path,
        now=datetime(2026, 7, 11, 8, tzinfo=timezone.utc),
    )

    assert not result.ok
    assert result.report_path.is_file()
    assert result.report["stages"][-1]["name"] == "provider_search"
    assert result.report["stages"][-1]["status"] == "failed"
    serialized = result.report_path.read_text(encoding="utf-8")
    assert "SECRET" not in serialized
    assert "HIDDEN" not in serialized
    assert "/srv/private/data" not in serialized
    assert "https://example.test/search" in serialized
