from __future__ import annotations

from marine_track.calibration import default_profile
from marine_track.telegram_calibration import (
    calibration_menu_markup,
    calibration_menu_text,
    calibration_task_markup,
    calibration_warning_text,
)
from marine_track.telegram_ui import ACTION_CALIBRATION, MENU_CALLBACK_PREFIX, main_menu_markup


def _button_texts(markup) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]


def test_admin_menu_shows_calibration_warning_entry() -> None:
    markup = main_menu_markup(is_admin=True, calibration_needed=True)
    buttons = [button for row in markup.inline_keyboard for button in row]

    calibration = next(button for button in buttons if "Калибровка" in button.text)
    assert calibration.callback_data == f"{MENU_CALLBACK_PREFIX}:{ACTION_CALIBRATION}"
    assert "⚠️" in calibration.text


def test_regular_user_menu_hides_calibration() -> None:
    markup = main_menu_markup(is_admin=False, calibration_needed=True)
    assert not any("Калибровка" in text for text in _button_texts(markup))


def test_calibration_text_distinguishes_training_metrics() -> None:
    profile = default_profile()
    profile["status"] = "collecting"
    profile["labels"]["usable"] = 3
    profile["labels"]["positive"] = 2
    profile["labels"]["negative"] = 1

    assert "сбор разметки" in calibration_menu_text(profile)
    assert "3/20" in calibration_menu_text(profile)
    assert "Требуется калибровка" in calibration_warning_text(profile)
    assert "Начать" not in " ".join(_button_texts(calibration_menu_markup(profile)))


def test_grid_keyboard_contains_all_cells_and_rejection_actions() -> None:
    texts = _button_texts(calibration_task_markup("0123456789abcdef"))

    for cell in range(1, 10):
        assert str(cell) in texts
    assert "🚫 Судна нет" in texts
    assert "❔ Не уверен" in texts
    assert "⏭ Пропустить" in texts
