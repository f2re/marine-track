from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.provider_canary import (
    compact_canary_aoi,
    run_sentinel1_canary,
    safe_error_message,
)
from marine_track.scene_materializer import AssetProbe


def write_aoi(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [[30.0, 43.0], [31.0, 43.0], [31.0, 44.0], [30.0, 44.0], [30.0, 43.0]]
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def fake_scene() -> Scene:
    asset = SceneAsset(
        key="vv",
        href="https://example.test/scene.tif?sig=secret-signature",
        media_type="image/tiff; application=geotiff; profile=cloud-optimized",
        roles=["data", "backscatter"],
        polarization="VV",
        units="sigma0",
        storage="https",
        auth_mode="runtime_signing",
    )
    return Scene(
        provider="planetary_computer",
        sensor=Sensor.SENTINEL1,
        product_id="S1_TEST_SCENE",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": asset.href},
        asset_metadata={"vv": asset},
        polarizations=["VV"],
    )


def fake_search_result(tmp_path: Path):
    scenes_json = tmp_path / "search" / "scenes.json"
    manifest = tmp_path / "search" / "assets.csv"
    scenes_json.parent.mkdir(parents=True, exist_ok=True)
    scenes_json.write_text("[]\n", encoding="utf-8")
    manifest.write_text("key,href\n", encoding="utf-8")
    return SimpleNamespace(
        provider="planetary_computer",
        sensor=Sensor.SENTINEL1,
        scenes=[fake_scene()],
        scenes_json=scenes_json,
        asset_manifest=manifest,
        cache_hit=False,
    )


def test_compact_canary_aoi_is_bounded_and_valid():
    payload = {
        "type": "Polygon",
        "coordinates": [
            [[30.0, 43.0], [31.0, 43.0], [31.0, 44.0], [30.0, 44.0], [30.0, 43.0]]
        ],
    }

    compact, metadata = compact_canary_aoi(payload, span_deg=0.08)

    assert compact["type"] == "FeatureCollection"
    assert metadata["area_km2"] > 0
    assert metadata["area_km2"] < 1000
    west, south, east, north = metadata["bbox"]
    assert east - west <= 0.080001
    assert north - south <= 0.080001
    assert len(metadata["hash"]) == 64


def test_asset_canary_probes_signed_asset_and_persists_redacted_report(tmp_path, monkeypatch):
    import marine_track.provider_canary as canary

    aoi = write_aoi(tmp_path / "default.geojson")
    output = tmp_path / "out"
    search_result = fake_search_result(tmp_path)
    seen: dict[str, object] = {}

    monkeypatch.setenv("SENTINELHUB_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setattr(canary, "search_detection_capable_scenes", lambda *args, **kwargs: search_result)

    def fake_access(href, provider, asset):
        seen["href"] = href
        seen["provider"] = provider
        seen["asset"] = asset.key
        return href, {"Authorization": "Bearer super-secret-value"}

    def fake_probe(href, *, headers=None, **kwargs):
        del kwargs
        assert "sig=secret-signature" in href
        assert headers == {"Authorization": "Bearer super-secret-value"}
        return AssetProbe(True, 206, "image/tiff", 4096, True)

    monkeypatch.setattr(canary, "prepare_asset_access", fake_access)
    monkeypatch.setattr(canary, "probe_raster_asset", fake_probe)

    result = run_sentinel1_canary(
        output_dir=output,
        default_aoi=aoi,
        mode="asset",
        lookback_hours=24,
        max_results=1,
        span_deg=0.05,
    )

    assert result.report["status"] == "success"
    assert result.report["asset"]["probe"]["range_supported"] is True
    assert seen["provider"] == "planetary_computer"
    report_text = result.report_path.read_text(encoding="utf-8")
    assert "super-secret-value" not in report_text
    assert "secret-signature" not in report_text
    assert "Authorization" not in report_text
    assert str(tmp_path) not in report_text
    assert stat.S_IMODE(result.report_path.stat().st_mode) == 0o600


def test_detection_canary_requires_confirmation_before_search(tmp_path, monkeypatch):
    import marine_track.provider_canary as canary

    aoi = write_aoi(tmp_path / "default.geojson")

    def forbidden_search(*args, **kwargs):
        raise AssertionError("search must not run before confirmation")

    monkeypatch.setattr(canary, "search_detection_capable_scenes", forbidden_search)
    result = run_sentinel1_canary(
        output_dir=tmp_path / "out",
        default_aoi=aoi,
        mode="detection",
        owner_user_id=100,
        owner_chat_id=200,
        confirm_detection=False,
    )

    assert result.report["status"] == "failed"
    assert result.report["error"]["type"] == "ProviderCanaryError"
    assert result.report["stages"] == []


def test_detection_canary_registers_scoped_scene_and_forces_wake_off(tmp_path, monkeypatch):
    import marine_track.provider_canary as canary

    aoi = write_aoi(tmp_path / "default.geojson")
    output = tmp_path / "out"
    search_result = fake_search_result(tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(canary, "search_detection_capable_scenes", lambda *args, **kwargs: search_result)
    monkeypatch.setattr(canary, "prepare_asset_access", lambda href, provider, asset: (href, {}))
    monkeypatch.setattr(
        canary,
        "probe_raster_asset",
        lambda *args, **kwargs: AssetProbe(True, 206, "image/tiff", 4096, True),
    )

    def fake_register(*args, **kwargs):
        captured["owner_user_id"] = kwargs["owner_user_id"]
        captured["owner_chat_id"] = kwargs["owner_chat_id"]
        captured["aoi"] = kwargs["aoi_geojson"]
        return ["scoped-token"]

    def fake_detection(**kwargs):
        captured["wake_enabled_override"] = kwargs["wake_enabled_override"]
        return SimpleNamespace(
            detections=[object(), object()],
            wake_research_enabled=False,
            materialized=SimpleNamespace(cropped=True, cache_hit=False),
            report_json=output / "detections" / "scoped-token" / "report.json",
            overview_png=output / "detections" / "scoped-token" / "overview.png",
        )

    monkeypatch.setattr(canary, "register_scenes", fake_register)
    monkeypatch.setattr(canary, "run_detection_for_token", fake_detection)

    result = run_sentinel1_canary(
        output_dir=output,
        default_aoi=aoi,
        mode="detection",
        owner_user_id=100,
        owner_chat_id=200,
        confirm_detection=True,
        lookback_hours=24,
        max_results=1,
    )

    assert result.report["status"] == "success"
    assert result.report["detection"]["candidate_count"] == 2
    assert result.report["detection"]["wake_research_enabled"] is False
    assert captured["wake_enabled_override"] is False
    assert captured["owner_user_id"] == 100
    assert captured["owner_chat_id"] == 200
    assert isinstance(captured["aoi"], dict)


def test_safe_error_message_redacts_secrets_urls_and_absolute_paths(monkeypatch):
    monkeypatch.setenv("CDSE_CLIENT_SECRET", "private-client-secret")
    error = RuntimeError(
        "failed https://example.test/a.tif?token=abc at /opt/marine_track/cache/a.tif "
        "using private-client-secret"
    )

    message = safe_error_message(error)

    assert "private-client-secret" not in message
    assert "token=abc" not in message
    assert "/opt/marine_track" not in message
    assert "[redacted]" in message
    assert "<local-path>" in message


@pytest.mark.parametrize("mode", ["unknown", "", "DETECTION-NOPE"])
def test_invalid_canary_mode_is_reported_without_network(tmp_path, monkeypatch, mode):
    import marine_track.provider_canary as canary

    aoi = write_aoi(tmp_path / "default.geojson")
    monkeypatch.setattr(
        canary,
        "search_detection_capable_scenes",
        lambda *args, **kwargs: pytest.fail("network stage must not run"),
    )

    result = run_sentinel1_canary(
        output_dir=tmp_path / f"out-{mode or 'empty'}",
        default_aoi=aoi,
        mode=mode,
    )

    assert result.report["status"] == "failed"
    assert result.report["stages"] == []
