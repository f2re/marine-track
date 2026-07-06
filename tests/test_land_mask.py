import json

import numpy as np
from rasterio.transform import from_origin

from marine_track.land_mask import apply_land_mask


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
