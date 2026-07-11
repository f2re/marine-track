from __future__ import annotations

import os
import time

import pytest

from marine_track.bounded_detection import (
    DetectionProcessError,
    DetectionTimeoutError,
    _apply_gdal_runtime_defaults,
    _run_worker_process,
)


def _success_worker(messages, value: object) -> None:
    messages.put(("progress", "stage"))
    messages.put(("result", value))


def _error_worker(messages) -> None:
    messages.put(("error", {"type": "RuntimeError", "message": "failed safely"}))


def _sleep_worker(messages) -> None:
    del messages
    time.sleep(30)


def test_worker_returns_result_and_forwards_progress() -> None:
    progress: list[str] = []

    result = _run_worker_process(
        _success_worker,
        ({"ok": True},),
        timeout_s=5,
        progress_callback=progress.append,
    )

    assert result == {"ok": True}
    assert progress == ["stage"]


def test_worker_error_is_typed() -> None:
    with pytest.raises(DetectionProcessError, match="RuntimeError: failed safely"):
        _run_worker_process(_error_worker, (), timeout_s=5)


def test_worker_timeout_terminates_stalled_process() -> None:
    started = time.monotonic()
    with pytest.raises(DetectionTimeoutError, match="was terminated"):
        _run_worker_process(_sleep_worker, (), timeout_s=0.25)
    assert time.monotonic() - started < 5


def test_gdal_defaults_are_bounded_and_do_not_override_operator_values(monkeypatch) -> None:
    managed = (
        "GDAL_DISABLE_READDIR_ON_OPEN",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS",
        "GDAL_HTTP_CONNECTTIMEOUT",
        "GDAL_HTTP_TIMEOUT",
        "GDAL_HTTP_LOW_SPEED_LIMIT",
        "GDAL_HTTP_LOW_SPEED_TIME",
        "GDAL_HTTP_MAX_RETRY",
        "GDAL_HTTP_RETRY_DELAY",
    )
    for name in managed:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GDAL_HTTP_TIMEOUT", "17")

    applied = _apply_gdal_runtime_defaults()

    assert applied["GDAL_DISABLE_READDIR_ON_OPEN"] == "EMPTY_DIR"
    assert applied["CPL_VSIL_CURL_ALLOWED_EXTENSIONS"] == ".tif,.tiff"
    assert applied["GDAL_HTTP_CONNECTTIMEOUT"] == "10"
    assert applied["GDAL_HTTP_TIMEOUT"] == "17"
    assert applied["GDAL_HTTP_LOW_SPEED_LIMIT"] == "1024"
    assert applied["GDAL_HTTP_LOW_SPEED_TIME"] == "30"
    assert applied["GDAL_HTTP_MAX_RETRY"] == "2"
    assert applied["GDAL_HTTP_RETRY_DELAY"] == "1"
    assert os.environ["GDAL_HTTP_TIMEOUT"] == "17"
