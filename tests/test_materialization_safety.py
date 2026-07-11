from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from marine_track.scene_materializer import (
    AssetProbe,
    MaterializationError,
    crop_raster_to_aoi,
    materialization_lock,
    materialize_asset,
)


def test_crop_preserves_aoi_and_source_valid_mask_without_source_nodata(tmp_path):
    source = tmp_path / "source.tif"
    image = np.arange(100, dtype="uint16").reshape(10, 10)
    with rasterio.open(
        source,
        "w",
        driver="GTiff",
        width=10,
        height=10,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(0.0, 10.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(image, 1)
        source_mask = np.full((10, 10), 255, dtype="uint8")
        source_mask[4, 4] = 0
        dataset.write_mask(source_mask)
        dataset.scales = (0.01,)
        dataset.offsets = (2.0,)
        dataset.update_tags(1, units="amplitude")

    target = tmp_path / "crop.tif"
    triangle = {
        "type": "Polygon",
        "coordinates": [[[1, 9], [8, 9], [1, 2], [1, 9]]],
    }
    crop_raster_to_aoi(str(source), target, triangle)

    with rasterio.open(target) as dataset:
        masked = dataset.read(1, masked=True)
        filled = dataset.read(1)
        assert dataset.nodata is not None and np.isnan(dataset.nodata)
        assert np.ma.getmaskarray(masked).any()
        assert np.isnan(filled).any()
        assert bool(masked.mask[3, 3]) is True  # source pixel (4, 4) after crop origin
        assert dataset.scales == (0.01,)
        assert dataset.offsets == (2.0,)
        assert dataset.tags(1).get("units") == "amplitude"


def test_concurrent_materialization_downloads_one_cache_target_once(tmp_path, monkeypatch):
    import marine_track.scene_materializer as materializer

    target = tmp_path / "cache" / "scene.tif"
    calls = 0
    calls_lock = threading.Lock()

    def fake_probe(href, **kwargs):
        del href, kwargs
        return AssetProbe(True, 206, "image/tiff", 4, True)

    def fake_download(url, path, **kwargs):
        nonlocal calls
        del url, kwargs
        with calls_lock:
            calls += 1
        time.sleep(0.15)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"II*\x00" + b"x" * 64)

    monkeypatch.setattr(materializer, "probe_raster_asset", fake_probe)
    monkeypatch.setattr(materializer, "download_url", fake_download)
    monkeypatch.setenv("MARINE_TRACK_RASTER_LOCK_TIMEOUT_S", "5")

    def run():
        return materialize_asset(
            "https://example.test/scene.tif",
            target,
            return_probe=True,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: run(), range(2)))

    assert calls == 1
    assert target.is_file()
    assert sorted([first[2], second[2]]) == [False, True]
    assert target.with_suffix(".tif.lock").is_file()


def test_corrupt_non_empty_cache_entry_is_rebuilt_under_lock(tmp_path, monkeypatch):
    import marine_track.scene_materializer as materializer

    target = tmp_path / "cache" / "scene.tif"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"not-a-tiff")
    downloads = 0

    def fake_probe(href, **kwargs):
        del kwargs
        path = str(href)
        if path == str(target) and target.read_bytes() == b"not-a-tiff":
            raise MaterializationError("corrupt cache")
        return AssetProbe(True, 206, "image/tiff", 4, True)

    def fake_download(url, path, **kwargs):
        nonlocal downloads
        del url, kwargs
        downloads += 1
        path.write_bytes(b"II*\x00" + b"x" * 64)

    monkeypatch.setattr(materializer, "probe_raster_asset", fake_probe)
    monkeypatch.setattr(materializer, "download_url", fake_download)

    result = materialize_asset("https://example.test/scene.tif", target)

    assert result == (target, False, False)
    assert downloads == 1
    assert target.read_bytes().startswith(b"II*\x00")


def test_materialization_lock_rejects_non_finite_timeout(tmp_path):
    with (
        pytest.raises(MaterializationError, match="finite and positive"),
        materialization_lock(tmp_path / "scene.tif", float("nan")),
    ):
        pass
