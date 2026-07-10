from __future__ import annotations

from datetime import datetime, timezone

import pytest

from marine_track.data_sources.stac_provider import STACProvider, default_stac_providers
from marine_track.models import Scene, SceneAsset, Sensor
from marine_track.scene_materializer import (
    MaterializationError,
    prepare_asset_access,
    probe_raster_asset,
    select_processing_asset,
    select_processing_asset_record,
)


class FakeAsset:
    def __init__(self, href, media_type=None, roles=None, title=None, extra_fields=None):
        self.href = href
        self.media_type = media_type
        self.roles = roles
        self.title = title
        self.extra_fields = extra_fields or {}


class FakeItem:
    id = "S1_TEST"
    datetime = datetime(2026, 7, 10, tzinfo=timezone.utc)
    collection_id = "sentinel-1-grd"
    properties = {
        "datetime": "2026-07-10T00:00:00Z",
        "sar:polarizations": ["VV", "VH"],
    }
    links = []
    assets = {
        "vv": FakeAsset(
            "s3://eodata/path/vv.tif",
            media_type="image/tiff; application=geotiff; profile=cloud-optimized",
            roles=["data"],
            extra_fields={
                "raster:bands": [{"unit": "amplitude", "nodata": 0, "scale": 1.0}],
                "alternate": {"https": {"href": "https://download.example/vv.tif?token=secret"}},
            },
        ),
        "thumbnail": FakeAsset(
            "https://example/preview.jpg",
            media_type="image/jpeg",
            roles=["thumbnail"],
        ),
    }


def test_legacy_asset_mapping_is_promoted_to_typed_contract():
    scene = Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="legacy",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": "/tmp/a.tif"},
    )
    assert scene.assets["vv"] == "/tmp/a.tif"
    assert scene.asset_records["vv"].href == "/tmp/a.tif"
    assert scene.asset_records["vv"].storage == "local"


def test_stac_provider_preserves_typed_asset_metadata_and_https_alternate():
    provider = STACProvider(
        "copernicus_cdse",
        "https://stac.dataspace.copernicus.eu/v1/",
        {Sensor.SENTINEL1: ["sentinel-1-grd"]},
    )
    scene = provider._item_to_scene(FakeItem(), Sensor.SENTINEL1)
    record = scene.asset_records["vv"]
    assert record.media_type.startswith("image/tiff")
    assert record.roles == ["data"]
    assert record.polarization == "VV"
    assert record.units == "amplitude"
    assert record.nodata == 0
    assert record.alternate_hrefs["https"].startswith("https://")
    selected = select_processing_asset_record(scene)
    assert selected is not None
    assert selected[0] == "vv"
    assert selected[2].startswith("https://download.example/")
    assert select_processing_asset(scene)[1].startswith("https://download.example/")


def test_current_cdse_defaults_and_collection_overrides(monkeypatch):
    monkeypatch.delenv("CDSE_STAC_URL", raising=False)
    monkeypatch.delenv("CDSE_STAC_SENTINEL1_COLLECTION", raising=False)
    monkeypatch.delenv("CDSE_STAC_SENTINEL2_COLLECTION", raising=False)
    cdse = default_stac_providers()[0]
    assert cdse.api_url == "https://stac.dataspace.copernicus.eu/v1/"
    assert cdse.collections[Sensor.SENTINEL1] == ["sentinel-1-grd"]
    assert cdse.collections[Sensor.SENTINEL2] == ["sentinel-2-l2a"]


def test_cdse_bearer_is_transient(monkeypatch):
    asset = SceneAsset(
        href="https://download.example/a.tif",
        media_type="image/tiff",
        roles=["data"],
        auth_mode="bearer",
    )
    monkeypatch.setattr("marine_track.scene_materializer.cdse_access_token", lambda: "secret-token")
    href, headers = prepare_asset_access(asset.href, "copernicus_cdse", asset)
    assert href == asset.href
    assert headers == {"Authorization": "Bearer secret-token"}
    assert "secret-token" not in asset.model_dump_json()


def test_local_range_probe_checks_tiff_magic(tmp_path):
    path = tmp_path / "a.tif"
    path.write_bytes(b"II*\x00" + b"x" * 64)
    probe = probe_raster_asset(str(path))
    assert probe.ok is True
    bad = tmp_path / "bad.tif"
    bad.write_bytes(b"not-a-tiff")
    with pytest.raises(MaterializationError, match="not a TIFF"):
        probe_raster_asset(str(bad))


def test_remote_probe_sends_range_and_auth(monkeypatch):
    captured = {}

    class Response:
        status = 206
        headers = {"Content-Type": "image/tiff", "Accept-Ranges": "bytes"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, size):
            return b"II*\x00" + b"x" * max(0, size - 4)

        def getcode(self):
            return self.status

    def fake_urlopen(request, timeout):
        captured["range"] = request.headers.get("Range")
        captured["authorization"] = request.headers.get("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("marine_track.scene_materializer.urlopen", fake_urlopen)
    probe = probe_raster_asset(
        "https://download.example/a.tif",
        headers={"Authorization": "Bearer token"},
        timeout=7,
        max_bytes=32,
    )
    assert probe.range_supported is True
    assert captured == {
        "range": "bytes=0-31",
        "authorization": "Bearer token",
        "timeout": 7,
    }


def test_preview_and_xml_sidecars_are_not_selected():
    scene = Scene(
        provider="copernicus_cdse",
        sensor=Sensor.SENTINEL1,
        product_id="x",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        asset_records={
            "thumbnail": SceneAsset(href="https://x/thumb.jpg", roles=["thumbnail"]),
            "calibration": SceneAsset(href="https://x/calibration.xml", roles=["metadata"]),
            "vv": SceneAsset(
                href="https://x/vv.tif",
                media_type="image/tiff",
                roles=["data"],
                polarization="VV",
            ),
        },
    )
    assert select_processing_asset(scene) == ("vv", "https://x/vv.tif")
