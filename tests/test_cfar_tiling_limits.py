from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from marine_track.calibration_areas import CALIBRATION_AREAS
from marine_track.detection import cfar_statistics
from marine_track.models import Sensor
from marine_track.pipeline import search_scenes_with_fallback
from marine_track.processing_config import load_effective_detector_config
from marine_track.raster_detection import _owned, _tile_windows, detect_candidates_from_raster
from marine_track.resource_limits import (
    ResourceLimitError,
    ResourceLimits,
    estimated_tile_count,
    load_resource_limits,
    validate_geojson_payload,
    validate_raster_workload,
)

ROOT = Path(__file__).resolve().parents[1]


def test_cfar_training_ring_excludes_guard_and_cut():
    image = np.ones((9, 9), dtype="float32")
    image[3:6, 3:6] = 50.0
    image[4, 4] = 100.0

    stats = cfar_statistics(
        image,
        threshold_sigma=3.0,
        local_window_px=7,
        guard_window_px=3,
        min_training_fraction=1.0,
    )

    assert stats.training_count[4, 4] == pytest.approx(40.0)
    assert stats.training_fraction[4, 4] == pytest.approx(1.0)
    assert stats.background_mean[4, 4] == pytest.approx(1.0)
    assert stats.background_std[4, 4] == pytest.approx(0.0, abs=1e-6)
    assert stats.threshold[4, 4] == pytest.approx(1.0)
    assert bool(stats.mask[4, 4]) is True
    assert bool(stats.edge[4, 4]) is False


def test_cfar_reports_nodata_and_geometric_edge_support():
    image = np.ones((9, 9), dtype="float32")
    image[4, 4] = 100.0
    image[1, 1] = np.nan
    stats = cfar_statistics(
        image,
        threshold_sigma=3.0,
        local_window_px=7,
        guard_window_px=3,
        min_training_fraction=0.5,
    )
    assert stats.training_count[4, 4] == pytest.approx(39.0)
    assert stats.training_fraction[4, 4] == pytest.approx(39.0 / 40.0)
    assert bool(stats.edge[4, 4]) is True

    corner = np.ones((9, 9), dtype="float32")
    corner[0, 0] = 100.0
    strict = cfar_statistics(
        corner,
        threshold_sigma=3.0,
        local_window_px=7,
        guard_window_px=3,
        min_training_fraction=0.5,
    )
    assert strict.training_fraction[0, 0] < 0.5
    assert bool(strict.edge[0, 0]) is True
    assert bool(strict.mask[0, 0]) is False


def test_tile_ownership_partitions_overlap_without_gaps_or_duplicates():
    windows = list(
        _tile_windows(
            160,
            128,
            tile_size_px=96,
            tile_overlap_px=32,
        )
    )
    assert len(windows) == 4
    for row in range(128):
        for col in range(160):
            owners = sum(_owned(row, col, window[4]) for window in windows)
            assert owners == 1


def test_tiled_detection_emits_boundary_candidate_once(tmp_path):
    height, width = 128, 160
    yy, xx = np.mgrid[0:height, 0:width]
    image = (xx + 0.25 * yy).astype("float32")
    image[63:66, 79:82] += 1000.0
    raster = tmp_path / "scene.tif"
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="float32",
        crs="EPSG:3857",
        transform=from_origin(0.0, 1280.0, 10.0, 10.0),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(image, 1)

    detections = detect_candidates_from_raster(
        raster,
        satellite="sentinel1",
        provider="test",
        product_id="TEST_SCENE",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        threshold_sigma=3.0,
        min_area_px=1,
        max_area_px=100,
        local_window_px=17,
        guard_window_px=5,
        min_training_fraction=1.0,
        tile_size_px=96,
        tile_overlap_px=32,
        normalization_sample_pixels=20_000,
        max_raster_pixels=100_000,
        max_tiles=10,
        max_candidates=100,
        calibration_profile={},
        phase2_output_dir=tmp_path / "state",
    )

    hits = [
        item
        for item in detections
        if abs(float(item.metadata["centroid_yx"][0]) - 64.0) <= 2.0
        and abs(float(item.metadata["centroid_yx"][1]) - 80.0) <= 2.0
    ]
    assert len(hits) == 1
    metadata = hits[0].metadata
    assert metadata["tile_count"] == 4
    assert metadata["training_fraction"] == pytest.approx(1.0)
    assert metadata["cfar_edge_flag"] is False
    assert metadata["bbox_yx"][0] <= 64 < metadata["bbox_yx"][2]
    assert metadata["bbox_yx"][1] <= 80 < metadata["bbox_yx"][3]


def test_resource_limits_validate_coordinates_topology_area_and_workload():
    small = {
        "type": "Polygon",
        "coordinates": [
            [[30.0, 43.0], [30.1, 43.0], [30.1, 43.1], [30.0, 43.1], [30.0, 43.0]]
        ],
    }
    metrics = validate_geojson_payload(small)
    assert 0.0 < metrics.area_km2 < 1_000.0
    assert metrics.vertex_count == 5

    with pytest.raises(ResourceLimitError, match="outside WGS84 bounds"):
        validate_geojson_payload(
            {"type": "Polygon", "coordinates": [[[181, 0], [181, 1], [179, 1], [181, 0]]]}
        )
    with pytest.raises(ResourceLimitError, match="topologically invalid"):
        validate_geojson_payload(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 1], [0, 1], [1, 0], [0, 0]]],
            }
        )
    with pytest.raises(ResourceLimitError, match="exceeds configured limit"):
        validate_geojson_payload(
            {
                "type": "Polygon",
                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
            },
            ResourceLimits(max_aoi_area_km2=1.0),
        )

    assert estimated_tile_count(160, 128, tile_size_px=96, tile_overlap_px=32) == 4
    with pytest.raises(ResourceLimitError, match="pixels"):
        validate_raster_workload(
            50,
            50,
            32,
            8,
            ResourceLimits(max_raster_pixels=1_000),
        )


def test_resource_limits_use_yaml_baseline_then_environment_override(tmp_path, monkeypatch):
    config = tmp_path / "processing.yaml"
    config.write_text(
        """
resource_limits:
  max_aoi_area_km2: 4321
  max_aoi_vertices: 321
  max_raster_pixels: 7654321
  max_tiles: 654
  max_candidates: 543
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("MARINE_TRACK_PROCESSING_CONFIG", str(config))

    baseline = load_resource_limits()
    assert baseline == ResourceLimits(
        max_aoi_area_km2=4321.0,
        max_aoi_vertices=321,
        max_raster_pixels=7_654_321,
        max_tiles=654,
        max_candidates=543,
    )

    monkeypatch.setenv("MARINE_TRACK_MAX_AOI_AREA_KM2", "1234")
    monkeypatch.setenv("MARINE_TRACK_MAX_TILES", "42")
    overridden = load_resource_limits()
    assert overridden.max_aoi_area_km2 == pytest.approx(1234.0)
    assert overridden.max_tiles == 42
    assert overridden.max_aoi_vertices == 321


def test_resource_limits_reject_malformed_present_processing_config(tmp_path, monkeypatch):
    config = tmp_path / "processing.yaml"
    config.write_text("resource_limits: []\n", encoding="utf-8")
    monkeypatch.setenv("MARINE_TRACK_PROCESSING_CONFIG", str(config))
    with pytest.raises(ResourceLimitError, match="resource_limits must be a mapping"):
        load_resource_limits()


def test_all_builtin_calibration_sectors_fit_default_aoi_limit():
    for area in CALIBRATION_AREAS:
        metrics = validate_geojson_payload(area.geojson())
        assert metrics.area_km2 <= ResourceLimits().max_aoi_area_km2, area.id


def test_oversized_aoi_is_rejected_before_provider_creation(tmp_path, monkeypatch):
    aoi = tmp_path / "large.geojson"
    aoi.write_text(
        '{"type":"Polygon","coordinates":[[[0,0],[2,0],[2,2],[0,2],[0,0]]]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MARINE_TRACK_MAX_AOI_AREA_KM2", "1")
    provider_called = False

    def forbidden_manager():
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider manager must not be built")

    monkeypatch.setattr("marine_track.pipeline.build_source_manager", forbidden_manager)
    with pytest.raises(ResourceLimitError, match="area"):
        search_scenes_with_fallback(
            config=object(),
            aoi=aoi,
            start=datetime(2026, 7, 1, tzinfo=timezone.utc),
            end=datetime(2026, 7, 2, tzinfo=timezone.utc),
            sensor=Sensor.SENTINEL1,
        )
    assert provider_called is False


def test_effective_config_includes_aoi_limits_and_two_sided_halo(monkeypatch):
    path = ROOT / "config" / "processing.yaml"
    baseline = load_effective_detector_config(Sensor.SENTINEL1, path=path)
    assert baseline.max_aoi_area_km2 == pytest.approx(25_000.0)
    assert baseline.max_aoi_vertices == 5_000

    monkeypatch.setenv("MARINE_TRACK_MAX_AOI_AREA_KM2", "1234")
    changed = load_effective_detector_config(Sensor.SENTINEL1, path=path)
    assert changed.max_aoi_area_km2 == pytest.approx(1234.0)
    assert changed.config_hash != baseline.config_hash

    with pytest.raises(ValueError, match="minimum is 30"):
        load_effective_detector_config(
            Sensor.SENTINEL1,
            path=path,
            local_window_px=31,
            tile_overlap_px=20,
        )
