from pathlib import Path

from marine_track.models import Sensor
from marine_track.telegram_config import TelegramBotConfig
from marine_track.telegram_ui import help_text, main_menu_markup, start_text, status_text


def make_config(tmp_path: Path) -> TelegramBotConfig:
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    return TelegramBotConfig(
        token="token",
        admin_ids={123},
        default_aoi=aoi,
        output_dir=tmp_path / "runs",
        default_sensor=Sensor.AUTO,
        default_lookback_hours=72,
        max_results=10,
        max_concurrent_jobs=1,
        detection_max_crops=10,
        land_mask_geojson=None,
        shoreline_buffer_m=500,
    )


def labels(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def test_main_menu_without_saved_bbox_has_no_area_shortcuts():
    markup = main_menu_markup(has_last_bbox=False, bbox_count=0)

    assert "🔎 Найти суда" in labels(markup)
    assert "↻ Повторить район" not in labels(markup)
    assert "📍 Мои районы" not in labels(markup)


def test_main_menu_with_one_bbox_has_quick_buttons():
    markup = main_menu_markup(has_last_bbox=True, bbox_count=1)

    assert "↻ Повторить район" in labels(markup)
    assert "🕒 Сроки района" in labels(markup)
    assert "📍 Мои районы" not in labels(markup)


def test_main_menu_with_multiple_bboxes_has_areas_button():
    markup = main_menu_markup(has_last_bbox=True, bbox_count=2)

    assert "📍 Мои районы" in labels(markup)
    assert "↻ Повторить район" not in labels(markup)


def test_start_help_status_text_render(tmp_path):
    config = make_config(tmp_path)

    assert "Marine Track" in start_text(config)
    assert "/areas" in help_text()
    assert "Статус Marine Track" in status_text(config, authorized=True, user_id=123)
