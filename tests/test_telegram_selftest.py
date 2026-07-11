from __future__ import annotations

from types import SimpleNamespace

from marine_track.telegram_selftest import (
    ACTION_DETECTION_CONFIRM,
    ACTION_DETECTION_RUN,
    SELFTEST_CALLBACK_PREFIX,
    detection_confirmation_markup,
    is_selftest_admin,
    selftest_menu_markup,
    selftest_result_text,
)
from marine_track.telegram_ui import main_menu_markup


def button_labels(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def button_callbacks(markup) -> list[str | None]:
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_admin_main_menu_and_selftest_menu_expose_safe_actions():
    admin_labels = button_labels(main_menu_markup(is_admin=True))
    user_labels = button_labels(main_menu_markup(is_admin=False))

    assert "🩺 Самопроверка" in admin_labels
    assert "🩺 Самопроверка" not in user_labels

    labels = button_labels(selftest_menu_markup())
    callbacks = button_callbacks(selftest_menu_markup())
    assert "🔌 Проверить provider и asset" in labels
    assert "🛰 Полный малый detection test" in labels
    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_DETECTION_CONFIRM}" in callbacks


def test_detection_selftest_requires_a_separate_confirmation_button():
    callbacks = button_callbacks(detection_confirmation_markup())
    assert f"{SELFTEST_CALLBACK_PREFIX}:{ACTION_DETECTION_RUN}" in callbacks
    assert f"{SELFTEST_CALLBACK_PREFIX}:open" in callbacks


def test_selftest_admin_check_is_strict_allowlist():
    update = SimpleNamespace(effective_user=SimpleNamespace(id=123))
    config = SimpleNamespace(admin_ids={123})
    assert is_selftest_admin(update, config) is True
    config = SimpleNamespace(admin_ids={999})
    assert is_selftest_admin(update, config) is False


def test_selftest_success_and_failure_messages_do_not_require_paths():
    success = selftest_result_text(
        {
            "status": "success",
            "mode": "asset",
            "scene": {"provider": "planetary_computer", "product_id": "S1_TEST"},
            "asset": {"probe": {"range_supported": True}},
            "stages": [{"name": "search", "status": "ok", "duration_ms": 42}],
        }
    )
    assert "Самопроверка завершена" in success
    assert "planetary_computer" in success
    assert "/opt/" not in success

    failure = selftest_result_text(
        {
            "status": "failed",
            "mode": "asset",
            "stages": [{"name": "asset_probe", "status": "failed", "duration_ms": 7}],
            "error": {"type": "MaterializationError", "message": "Telegram HTTP 403"},
        }
    )
    assert "Самопроверка не пройдена" in failure
    assert "asset_probe" in failure
    assert "MaterializationError" in failure
