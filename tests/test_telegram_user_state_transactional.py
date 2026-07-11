from __future__ import annotations

import json
import multiprocessing
import stat
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from marine_track.models import Sensor
from marine_track.telegram_user_state import (
    OUTPUT_MODE_FILES,
    OUTPUT_MODE_IMAGES,
    STATE_SCHEMA_VERSION,
    UserStateSchemaError,
    get_output_mode,
    get_saved_bboxes,
    inspect_user_state,
    load_state,
    quarantine_paths,
    save_last_bbox,
    save_state,
    set_output_mode,
    state_lock_path,
    state_path,
)


def _parallel_save_same_bbox(output_dir: str, loops: int) -> int:
    root = Path(output_dir)
    for _ in range(loops):
        save_last_bbox(
            root,
            user_id=1001,
            sensor=Sensor.SENTINEL1,
            west=30.0,
            south=43.0,
            east=30.1,
            north=43.1,
            hours=72,
        )
    return loops


def test_legacy_state_is_read_and_next_write_is_atomic_versioned_and_private(tmp_path):
    legacy = {
        "users": {
            "42": {
                "output_mode": OUTPUT_MODE_IMAGES,
                "saved_bboxes": [],
            }
        }
    }
    path = state_path(tmp_path)
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert get_output_mode(tmp_path, 42) == OUTPUT_MODE_IMAGES
    assert load_state(tmp_path).get("schema_version") is None
    inspection = inspect_user_state(tmp_path)
    assert inspection.valid
    assert inspection.schema_version == 0
    assert "legacy" in inspection.detail

    assert set_output_mode(tmp_path, 42, OUTPUT_MODE_FILES) == OUTPUT_MODE_FILES
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = path.read_bytes()

    assert payload["schema_version"] == STATE_SCHEMA_VERSION
    assert payload["users"]["42"]["output_mode"] == OUTPUT_MODE_FILES
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(state_lock_path(tmp_path).stat().st_mode) == 0o600


def test_corrupt_state_is_quarantined_before_new_state_is_written(tmp_path):
    path = state_path(tmp_path)
    corrupt = b'{"users":{"42":'
    path.write_bytes(corrupt)

    assert set_output_mode(tmp_path, 42, OUTPUT_MODE_IMAGES) == OUTPUT_MODE_IMAGES

    quarantined = quarantine_paths(tmp_path)
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == corrupt
    assert stat.S_IMODE(quarantined[0].stat().st_mode) == 0o600
    assert get_output_mode(tmp_path, 42) == OUTPUT_MODE_IMAGES
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == STATE_SCHEMA_VERSION


def test_explicit_state_replacement_quarantines_corrupt_active_document(tmp_path):
    path = state_path(tmp_path)
    corrupt = b"{broken"
    path.write_bytes(corrupt)

    save_state(
        tmp_path,
        {"users": {"7": {"output_mode": OUTPUT_MODE_FILES}}},
    )

    quarantined = quarantine_paths(tmp_path)
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == corrupt
    assert get_output_mode(tmp_path, 7) == OUTPUT_MODE_FILES


def test_plain_reader_quarantines_invalid_root_instead_of_silently_overwriting(tmp_path):
    path = state_path(tmp_path)
    path.write_text("[]\n", encoding="utf-8")

    assert load_state(tmp_path) == {}
    assert not path.exists()
    quarantined = quarantine_paths(tmp_path)
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == "[]\n"


def test_future_schema_fails_closed_without_quarantine_or_overwrite(tmp_path):
    path = state_path(tmp_path)
    original = b'{"schema_version":2,"users":{"42":{"output_mode":"images"}}}\n'
    path.write_bytes(original)

    with pytest.raises(UserStateSchemaError, match="unsupported schema_version 2"):
        set_output_mode(tmp_path, 42, OUTPUT_MODE_FILES)

    assert path.read_bytes() == original
    assert quarantine_paths(tmp_path) == []
    inspection = inspect_user_state(tmp_path)
    assert inspection.exists
    assert not inspection.valid
    assert "unsupported schema_version 2" in inspection.detail


def test_parallel_process_updates_do_not_lose_bbox_use_count(tmp_path):
    workers = 4
    loops = 8
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=context) as executor:
        completed = list(
            executor.map(
                _parallel_save_same_bbox,
                [str(tmp_path)] * workers,
                [loops] * workers,
            )
        )

    assert completed == [loops] * workers
    saved = get_saved_bboxes(tmp_path, 1001)
    assert len(saved) == 1
    assert saved[0].use_count == workers * loops
    inspection = inspect_user_state(tmp_path)
    assert inspection.valid
    assert inspection.user_count == 1
    assert inspection.quarantine_count == 0
    assert not list(tmp_path.glob(".telegram_user_state.json.tmp-*"))


def test_inspection_reports_corruption_without_leaking_path(tmp_path):
    path = state_path(tmp_path)
    path.write_text("{broken", encoding="utf-8")

    inspection = inspect_user_state(tmp_path)

    assert inspection.exists
    assert not inspection.valid
    assert inspection.user_count == 0
    assert "invalid JSON" in inspection.detail
    assert str(tmp_path) not in inspection.detail
