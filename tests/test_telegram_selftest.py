from __future__ import annotations

from marine_track.telegram_selftest import (
    ACTION_ASSET,
    ACTION_CONFIRM_DETECTION,
    ACTION_RUN_DETECTION,
    SELFTEST_CALLBACK_PREFIX,
    detection_confirmation_markup,
    detection_confirmation_text,
    format_canary_report,
    selftest_menu_markup,
)
from marine_track.telegram_ui import main_menu_markup


def callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_selftest_callbacks_are_short_and_confirmation_is_separate():
    menu = callbacks(selftest_menu_markup())
    confirmation = callbacks(detection_confirmation_markup())

    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_ASSET}" in menu
    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_CONFIRM_DETECTION}" in menu
    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_RUN_DETECTION}" not in menu
    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_RUN_DETECTION}" in confirmation
    assert all(len(value.encode("utf-8")) <= 64 for value in menu + confirmation)
    assert "provider quota" in detection_confirmation_text()
    assert "принудительно отключён" in detection_confirmation_text()


def test_admin_main_menu_exposes_selftest():
    labels = [
        button.text
        for row in main_menu_markup(is_admin=True).inline_keyboard
        for button in row
    ]
    assert "🩺 Self-test" in labels
    assert "🩺 Self-test" not in [
        button.text
        for row in main_menu_markup(is_admin=False).inline_keyboard
        for button in row
    ]


def test_report_formatter_uses_only_redacted_report_fields():
    text = format_canary_report(
        {
            "status": "passed",
            "mode": "detection",
            "duration_ms": 1234,
            "aoi": {"source": "derived_from_default_aoi", "area_km2": 64.0},
            "result": {
                "search": {
                    "provider": "planetary_computer",
                    "scene_count": 2,
                    "acquisition_time": "2026-07-11T00:00:00+00:00",
                },
                "asset": {
                    "key": "vv",
                    "access_mode": "runtime_signed_url",
                    "probe": {
                        "status": 206,
                        "range_supported": True,
                        "bytes_checked": 4096,
                    },
                },
                "detection": {
                    "candidate_count": 3,
                    "aoi_cropped": True,
                    "preprocessing_domain": "relative_db",
                    "calibration_status": "relative_uncalibrated_amplitude",
                    "wake_research_enabled": False,
                },
            },
            "stages": [
                {"name": "provider_search", "status": "passed", "duration_ms": 800}
            ],
        }
    )

    assert "planetary_computer" in text
    assert "candidates: <code>3</code>" in text
    assert "wake research: <code>disabled</code>" in text
    assert "/opt/" not in text
    assert "token=" not in text
