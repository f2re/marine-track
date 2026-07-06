from marine_track.data_sources.sentinelhub_provider import SentinelHubProvider
from marine_track.models import Sensor


def test_sentinelhub_feature_to_scene_collects_assets():
    provider = SentinelHubProvider(catalog_url="https://example.test/catalog")
    feature = {
        "id": "S2_TEST",
        "properties": {
            "datetime": "2026-07-06T05:00:00Z",
            "eo:cloud_cover": 12.0,
        },
        "geometry": {"type": "Point", "coordinates": [37.0, 44.0]},
        "assets": {
            "thumbnail": {"href": "https://example.test/thumb.jpg"},
            "B04": {"href": "https://example.test/B04.tif"},
        },
    }
    scene = provider._feature_to_scene(feature, Sensor.SENTINEL2)
    assert scene.provider == "sentinelhub"
    assert scene.product_id == "S2_TEST"
    assert scene.assets["B04"].endswith("B04.tif")
    assert scene.cloud_cover == 12.0
