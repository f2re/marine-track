from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.transform import from_origin

from marine_track.detection_pipeline import run_detection_for_token
from marine_track.models import Scene, Sensor
from marine_track.scene_materializer import materialize_scene_from_token, select_processing_asset
from marine_track.telegram_scene_browser import register_scenes

OWNER_USER_ID = 100
OWNER_CHAT_ID = 200


def write_test_raster(path):
    data = np.zeros((64, 64), dtype="float32")
    data[20:23, 30:33] = 100.0
    transform = from_origin(10.0, 20.0, 0.01, 0.01)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[0],
        width=data.shape[1],
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(data, 1)
    return path


def make_scene(raster_path) -> Scene:
    return Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="LOCAL_TEST_SCENE",
        acquisition_time=datetime(2026, 7, 6, 5, 0, tzinfo=timezone.utc),
        assets={"vv": str(raster_path), "thumbnail": "https://example.test/thumb.jpg"},
    )


def register_test_scene(tmp_path, scene):
    return register_scenes(
        output_dir=tmp_path,
        provider=scene.provider,
        sensor=scene.sensor,
        scenes=[scene],
        scenes_json=tmp_path / "scenes.json",
        asset_manifest=tmp_path / "assets.csv",
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
    )[0]


def test_select_processing_asset_skips_preview(tmp_path):
    raster = write_test_raster(tmp_path / "scene.tif")
    scene = make_scene(raster)
    key, href = select_processing_asset(scene)
    assert key == "vv"
    assert href.endswith("scene.tif")


def test_materialize_scene_from_token(tmp_path):
    raster = write_test_raster(tmp_path / "scene.tif")
    scene = make_scene(raster)
    token = register_test_scene(tmp_path, scene)
    materialized = materialize_scene_from_token(
        token,
        tmp_path,
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
    )
    assert materialized.raster_path.is_file()
    assert materialized.raster_key == "vv"
    assert materialized.scene.product_id == "LOCAL_TEST_SCENE"


def test_run_detection_for_token_outputs_files(tmp_path):
    raster = write_test_raster(tmp_path / "scene.tif")
    scene = make_scene(raster)
    token = register_test_scene(tmp_path, scene)
    result = run_detection_for_token(
        token,
        tmp_path,
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
        threshold_sigma=1.0,
        local_window_px=0,
    )
    assert result.overview_png.is_file()
    assert result.geojson.is_file()
    assert result.csv.is_file()
    assert result.parquet.is_file()
    assert result.report_json.is_file()
    assert result.runtime_state_json.is_file()
    assert result.runtime_state_json.stat().st_mode & 0o777 == 0o600
    assert len(result.detections) >= 1
    assert len(result.crop_pngs) >= 1
    assert result.crop_pngs[0].is_file()
    assert result.preprocessing_plan.sensor == "sentinel1"
    assert result.preprocessing_plan.output_domain == "relative_backscatter_db"
    assert result.wake_research_enabled is False
    assert all(item.research_proxies.kelvin_speed is None for item in result.detections)
