import json

import numpy as np
from pyproj import Transformer
from rasterio.transform import from_origin

from marine_track.land_mask import apply_land_mask, prepare_land_mask


def test_apply_land_mask_sets_polygon_pixels_to_nan(tmp_path):
    mask_path = tmp_path / "land.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [10.4, 20.0], [10.4, 19.6], [10.0, 19.6], [10.0, 20.0]]],
                },
            }
        ],
    }
    mask_path.write_text(json.dumps(payload), encoding="utf-8")
    image = np.ones((100, 100), dtype="float32")
    transform = from_origin(10.0, 20.0, 0.01, 0.01)

    masked = apply_land_mask(image, transform, "EPSG:4326", mask_path, shoreline_buffer_m=0)

    assert np.isnan(masked[10, 10])
    assert np.isfinite(masked[80, 80])


def test_prepare_land_mask_clips_global_features_to_raster_bounds(tmp_path):
    mask_path = tmp_path / "global-land.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "black-sea-coast"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[33.0, 43.0], [34.0, 43.0], [34.0, 44.0], [33.0, 44.0], [33.0, 43.0]]
                    ],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "far-away"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[-75.0, -75.0], [-74.0, -75.0], [-74.0, -74.0], [-75.0, -74.0], [-75.0, -75.0]]
                    ],
                },
            },
        ],
    }
    mask_path.write_text(json.dumps(payload), encoding="utf-8")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    minx, miny = transformer.transform(33.2, 43.2)
    maxx, maxy = transformer.transform(33.8, 43.8)

    prepared = prepare_land_mask(
        mask_path,
        "EPSG:32636",
        shoreline_buffer_m=500,
        raster_bounds=(minx, miny, maxx, maxy),
    )

    assert prepared is not None
    assert len(prepared.geometries) == 1
