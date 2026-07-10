from marine_track.telegram_calibration import calibration_menu_markup
from marine_track.telegram_calibration_phase2 import (
    PHASE2_CALLBACK_PREFIX,
    object_markup,
    phase2_menu_markup,
)


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


def test_phase1_menu_links_phase2():
    markup = calibration_menu_markup({"status": "collecting"})
    assert f"{PHASE2_CALLBACK_PREFIX}:p2open" in _callbacks(markup)


def test_phase2_object_markup_contains_extended_answers():
    callbacks = _callbacks(object_markup("task"))
    assert f"{PHASE2_CALLBACK_PREFIX}:p2object:task:none" in callbacks
    assert f"{PHASE2_CALLBACK_PREFIX}:p2object:task:multiple" in callbacks
    assert len([value for value in callbacks if ":p2object:task:" in value]) == 13


def test_phase2_menu_has_promotion_and_rollback():
    callbacks = _callbacks(phase2_menu_markup())
    assert f"{PHASE2_CALLBACK_PREFIX}:p2promote" in callbacks
    assert f"{PHASE2_CALLBACK_PREFIX}:p2rollback" in callbacks
