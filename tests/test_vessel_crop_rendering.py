from __future__ import annotations

from datetime import datetime, timezone

import cv2
import numpy as np
import rasterio
from rasterio.transform import from_origin, xy

from marine_track.models import VesselDetection
from marine_track.rendering.vessel_crop import render_vessel_crop


def test_crop_centers_candidate_near_raster_edge(tmp_path) -> None:
    raster_path = tmp_path / "edge.tif"
    transform = from_origin(30.0, 45.0, 0.001, 0.001)
    image = np.full((64, 64), 0.01, dtype="float32")
    image[2:5, 2:5] = 1.0
    with rasterio.open(
        raster_path,
        "w",
        driver="GTiff",
        width=64,
        height=64,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=transform,
    ) as dataset:
        dataset.write(image, 1)
    lon, lat = xy(transform, 3, 3)
    detection = VesselDetection(
        detection_id="edge-candidate",
        lon=lon,
        lat=lat,
        satellite="sentinel1",
        provider="local",
        product_id="edge-scene",
        acquisition_time=datetime(2026, 7, 15, tzinfo=timezone.utc),
        ranking_score=0.8,
    )

    output = render_vessel_crop(
        raster_path,
        detection,
        tmp_path / "crop.png",
        index=1,
        crop_size_px=32,
        output_size_px=256,
    )

    rendered = cv2.imread(str(output))
    assert rendered.shape == (256, 256, 3)
    center = rendered[112:145, 112:145]
    red_marker = (center[:, :, 2] > 200) & (center[:, :, 1] < 80)
    assert red_marker.any()
