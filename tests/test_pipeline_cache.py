from datetime import datetime, timezone

from marine_track.models import Scene, Sensor
from marine_track.pipeline import run_search_stage


def test_run_search_stage_reuses_scene_search_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MARINE_TRACK_CACHE_DIR", str(tmp_path / "cache"))
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(
        '{"type":"Polygon","coordinates":[[[30,43],[30.1,43],[30.1,43.1],[30,43.1],[30,43]]]}',
        encoding="utf-8",
    )
    start = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    calls = {"count": 0}

    def fake_search_scenes_with_fallback(**kwargs):
        calls["count"] += 1
        return (
            "fake",
            Sensor.SENTINEL1,
            [
                Scene(
                    provider="fake",
                    sensor=Sensor.SENTINEL1,
                    product_id="SCENE_1",
                    acquisition_time=start,
                )
            ],
        )

    monkeypatch.setattr("marine_track.pipeline.load_config", lambda: object())
    monkeypatch.setattr("marine_track.pipeline.search_scenes_with_fallback", fake_search_scenes_with_fallback)

    first = run_search_stage(aoi, start, end, Sensor.SENTINEL1, tmp_path / "run1", max_results=5)
    second = run_search_stage(aoi, start, end, Sensor.SENTINEL1, tmp_path / "run2", max_results=5)

    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls["count"] == 1
    assert second.scene_count == 1
    assert second.scenes_json.is_file()
