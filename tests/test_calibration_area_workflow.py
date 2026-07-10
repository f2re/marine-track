from __future__ import annotations

import json
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from marine_track.calibration_area_pipeline import (
    load_search_session,
    prepare_calibration_data,
    search_calibration_scenes,
    search_sessions_dir,
    session_tokens,
)
from marine_track.calibration_areas import (
    AREA_GROUPS,
    AREA_PAGE_SIZE,
    CALIBRATION_AREAS,
    areas_for_group,
    paginate_areas,
    validate_catalog,
)
from marine_track.calibration_phase2 import Phase2Targets
from marine_track.models import Scene, Sensor
from marine_track.telegram_calibration import calibration_menu_markup
from marine_track.telegram_calibration_areas import (
    ACTION_AREA_HOME,
    _cb,
    area_home_markup,
    preparation_result_markup,
    resolve_area,
)
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_user_state import save_last_bbox


def make_config(tmp_path: Path) -> TelegramBotConfig:
    default_aoi = tmp_path / "default.geojson"
    default_aoi.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[[36.5, 43.8], [38.0, 43.8], [38.0, 44.8], [36.5, 44.8], [36.5, 43.8]]]
                            ],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return TelegramBotConfig(
        token="token",
        admin_ids={100},
        default_aoi=default_aoi,
        output_dir=tmp_path / "output",
        default_sensor=Sensor.AUTO,
        default_lookback_hours=72,
        max_results=10,
        max_concurrent_jobs=1,
        detection_max_crops=10,
        land_mask_geojson=None,
        shoreline_buffer_m=500,
    )


def button_labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_catalog_is_large_valid_grouped_and_paged():
    assert len(CALIBRATION_AREAS) >= 80
    assert validate_catalog() == []
    assert {area.group_id for area in CALIBRATION_AREAS} == {group.id for group in AREA_GROUPS}
    for group in AREA_GROUPS:
        areas = areas_for_group(group.id)
        assert areas
        shown, page, page_count = paginate_areas(areas, 0)
        assert page == 0
        assert page_count >= 1
        assert 1 <= len(shown) <= AREA_PAGE_SIZE


def test_all_generated_callback_data_fits_telegram_limit():
    for area in CALIBRATION_AREAS:
        values = (
            _cb("aselect", f"b.{area.id}"),
            _cb("asensor", f"b.{area.id}", "s1"),
            _cb("asearch", f"b.{area.id}", "s1", "720"),
        )
        assert all(len(value.encode("utf-8")) <= 64 for value in values)


def test_calibration_menu_exposes_area_acquisition(tmp_path):
    profile = {"status": "not_started"}
    assert "🗺 Выбрать акваторию и найти сцены" in button_labels(calibration_menu_markup(profile))
    config = make_config(tmp_path)
    assert f"mtcal:{ACTION_AREA_HOME}" in [
        button.callback_data
        for row in area_home_markup(config, 100).inline_keyboard
        for button in row
    ]


def test_resolve_builtin_default_and_saved_areas(tmp_path):
    config = make_config(tmp_path)
    builtin = resolve_area(config, 100, "b.bs_w")
    assert builtin["source"] == "built_in_catalog"
    assert builtin["bbox"] == (28.5, 42.0, 30.5, 43.0)

    default = resolve_area(config, 100, "default")
    assert default["source"] == "default_aoi"
    assert default["bbox"] == (36.5, 43.8, 38.0, 44.8)

    saved = save_last_bbox(
        config.output_dir,
        100,
        Sensor.SENTINEL1,
        10.0,
        20.0,
        11.0,
        21.0,
        168,
    )
    resolved = resolve_area(config, 100, f"s.{saved.id}")
    assert resolved["source"] == "saved_bbox"
    assert resolved["bbox"] == (10.0, 20.0, 11.0, 21.0)


def test_search_session_is_atomic_scoped_and_contains_tokens(tmp_path, monkeypatch):
    import marine_track.calibration_area_pipeline as pipeline

    output_dir = tmp_path / "output"
    scene = Scene(
        provider="local",
        sensor=Sensor.SENTINEL1,
        product_id="scene-1",
        acquisition_time=datetime(2026, 7, 10, tzinfo=timezone.utc),
        assets={"vv": str(tmp_path / "scene.tif")},
    )
    scenes_json = tmp_path / "scenes.json"
    scenes_json.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        pipeline,
        "search_detection_capable_scenes",
        lambda *args, **kwargs: SimpleNamespace(
            provider="local",
            sensor=Sensor.SENTINEL1,
            scenes=[scene],
            scenes_json=scenes_json,
            asset_manifest=None,
            cache_hit=False,
        ),
    )
    monkeypatch.setattr(pipeline, "register_scenes", lambda *args, **kwargs: ["token-1"])

    session = search_calibration_scenes(
        output_dir=output_dir,
        area_id="test",
        area_name="Test water",
        area_source="test",
        aoi_geojson=CALIBRATION_AREAS[0].geojson(),
        sensor=Sensor.SENTINEL1,
        hours=168,
        max_results=5,
        owner_user_id=100,
        owner_chat_id=200,
    )
    path = search_sessions_dir(output_dir) / f"{session['session_id']}.json"
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert session_tokens(session) == ["token-1"]
    assert load_search_session(
        output_dir,
        session["session_id"],
        owner_user_id=100,
        owner_chat_id=200,
    )["area"]["name"] == "Test water"
    with pytest.raises(PermissionError):
        load_search_session(
            output_dir,
            session["session_id"],
            owner_user_id=101,
            owner_chat_id=200,
        )


def test_zero_candidates_still_generates_phase2_tasks(tmp_path, monkeypatch):
    import marine_track.calibration_area_pipeline as pipeline

    report = tmp_path / "report.json"
    overview = tmp_path / "overview.png"
    report.write_text("{}", encoding="utf-8")
    overview.write_bytes(b"png")
    monkeypatch.setattr(
        pipeline,
        "run_detection_for_token",
        lambda **kwargs: SimpleNamespace(
            detections=[],
            report_json=report,
            overview_png=overview,
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "generate_independent_tasks",
        lambda *args, **kwargs: {"tasks": [{"task_id": "tile-1"}]},
    )
    result = prepare_calibration_data(
        output_dir=tmp_path / "output",
        tokens=["token-1"],
        owner_user_id=100,
        owner_chat_id=200,
        max_crops=0,
        land_mask_geojson=None,
        shoreline_buffer_m=0,
        phase2_targets=Phase2Targets(),
    )
    assert result.candidate_count == 0
    assert result.phase2_task_count == 1
    assert "🌊 Размечать независимые tiles" in button_labels(preparation_result_markup(0))
    assert "🧪 Размечать candidates" not in button_labels(preparation_result_markup(0))
