import json

from marine_track.land_mask_update import update_land_mask


def test_update_land_mask_from_local_geojson(tmp_path):
    source = tmp_path / "source.geojson"
    output = tmp_path / "land.geojson"
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "test_land"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[10.0, 20.0], [10.2, 20.0], [10.2, 19.8], [10.0, 19.8], [10.0, 20.0]]],
                },
            }
        ],
    }
    source.write_text(json.dumps(payload), encoding="utf-8")

    result = update_land_mask(output_path=output, source=source, cache_dir=tmp_path / "cache", force=True)

    assert result.output_path == output
    assert result.feature_count == 1
    assert output.is_file()
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["type"] == "FeatureCollection"
    assert len(written["features"]) == 1
