from datetime import datetime, timezone

import numpy as np
import rasterio
from rasterio.transform import from_origin

from marine_track.models import Scene, Sensor
from marine_track.scene_materializer import materialize_scene_from_token
from marine_track.telegram_scene_browser import register_scenes

OWNER_USER_ID = 100
OWNER_CHAT_ID = 200


def write_raster(path):
    data = np.ones((100, 100), dtype="float32")
    transform = from_origin(10.0, 20.0, 0.01, 0.01)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=100,
        width=100,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(data, 1)
    return path


def aoi_geojson():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[10.2, 19.8], [10.5, 19.8], [10.5, 19.5], [10.2, 19.5], [10.2, 19.8]]
                    ],
                },
            }
        ],
    }


def test_materializer_crops_to_registry_aoi(tmp_path):
    raster = write_raster(tmp_path / "scene.tif")
    scene = Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="LOCAL_CROP_TEST",
        acquisition_time=datetime(2026, 7, 6, 5, 0, tzinfo=timezone.utc),
        assets={"vv": str(raster)},
    )
    token = register_scenes(
        output_dir=tmp_path,
        provider="local",
        sensor=Sensor.SENTINEL1,
        scenes=[scene],
        scenes_json=tmp_path / "scenes.json",
        asset_manifest=tmp_path / "assets.csv",
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
        aoi_geojson=aoi_geojson(),
    )[0]
    materialized = materialize_scene_from_token(
        token,
        tmp_path,
        owner_user_id=OWNER_USER_ID,
        owner_chat_id=OWNER_CHAT_ID,
    )
    assert materialized.cropped is True
    with rasterio.open(materialized.raster_path) as dataset:
        assert dataset.width < 100
        assert dataset.height < 100
