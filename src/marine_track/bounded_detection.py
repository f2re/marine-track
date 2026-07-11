from __future__ import annotations

import math
import multiprocessing
import os
import queue
import time
from collections.abc import Callable
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from marine_track.detection_pipeline import DetectionRunResult, run_detection_for_token
from marine_track.provenance import redact_value
from marine_track.scene_materializer import MaterializationError

ProgressCallback = Callable[[str], None]
DEFAULT_DETECTION_JOB_TIMEOUT_S = 300.0


class DetectionProcessError(RuntimeError):
    """Raised when an isolated detection worker fails or exits unexpectedly."""


class DetectionTimeoutError(DetectionProcessError):
    """Raised after a stalled detection worker has been terminated."""


def configured_detection_timeout_s(explicit: float | None = None) -> float:
    raw: str | float = (
        explicit
        if explicit is not None
        else os.getenv(
            "MARINE_TRACK_DETECTION_JOB_TIMEOUT_S",
            str(DEFAULT_DETECTION_JOB_TIMEOUT_S),
        )
    )
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DetectionProcessError(
            "MARINE_TRACK_DETECTION_JOB_TIMEOUT_S must be numeric"
        ) from exc
    if not math.isfinite(value) or not 10.0 <= value <= 3600.0:
        raise DetectionProcessError(
            "MARINE_TRACK_DETECTION_JOB_TIMEOUT_S must be finite and in [10, 3600]"
        )
    return value


def run_detection_in_subprocess(
    *,
    token: str,
    output_dir: Path,
    owner_user_id: int,
    owner_chat_id: int,
    max_crops: int = 10,
    threshold_sigma: float | None = None,
    min_area_px: int | None = None,
    max_area_px: int | None = None,
    local_window_px: int | None = None,
    guard_window_px: int | None = None,
    min_contrast_sigma: float | None = None,
    land_mask_geojson: str | Path | None = None,
    shoreline_buffer_m: float = 0.0,
    wake_research: bool | None = None,
    timeout_s: float | None = None,
    progress_callback: ProgressCallback | None = None,
) -> DetectionRunResult:
    """Run one detection job in a killable process with a hard wall-clock limit.

    Rasterio/GDAL may block in native network I/O and cannot be safely cancelled by
    cancelling ``asyncio.to_thread``. Running the complete job in a spawned process
    lets the Telegram worker terminate a stalled materialization without leaving an
    unbounded background thread in the bot process.
    """

    kwargs: dict[str, Any] = {
        "token": token,
        "output_dir": output_dir,
        "owner_user_id": owner_user_id,
        "owner_chat_id": owner_chat_id,
        "max_crops": max_crops,
        "threshold_sigma": threshold_sigma,
        "min_area_px": min_area_px,
        "max_area_px": max_area_px,
        "local_window_px": local_window_px,
        "guard_window_px": guard_window_px,
        "min_contrast_sigma": min_contrast_sigma,
        "land_mask_geojson": land_mask_geojson,
        "shoreline_buffer_m": shoreline_buffer_m,
        "wake_research": wake_research,
    }
    payload = _run_worker_process(
        _detection_worker,
        (kwargs,),
        timeout_s=configured_detection_timeout_s(timeout_s),
        progress_callback=progress_callback,
    )
    if not isinstance(payload, DetectionRunResult):
        raise DetectionProcessError("detection worker returned an invalid result")
    return payload


def _run_worker_process(
    worker,
    worker_args: tuple[object, ...],
    *,
    timeout_s: float,
    progress_callback: ProgressCallback | None = None,
    context_name: str = "spawn",
) -> object:
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("worker timeout must be finite and positive")

    context = multiprocessing.get_context(context_name)
    messages = context.Queue()
    # Typeshed does not expose the dynamically selected context's Process factory.
    process: BaseProcess = context.Process(  # type: ignore[attr-defined]
        target=worker,
        args=(messages, *worker_args),
        name="marine-track-detection",
        daemon=False,
    )
    process.start()
    deadline = time.monotonic() + timeout_s
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process(process)
                raise DetectionTimeoutError(
                    f"candidate detection exceeded {timeout_s:.0f}s and was terminated"
                )
            try:
                message = messages.get(timeout=min(0.25, remaining))
            except queue.Empty:
                if process.is_alive():
                    continue
                process.join(timeout=1.0)
                try:
                    message = messages.get(timeout=0.5)
                except queue.Empty as exc:
                    raise DetectionProcessError(
                        f"detection worker exited with code {process.exitcode} without a result"
                    ) from exc

            if not isinstance(message, tuple) or len(message) != 2:
                raise DetectionProcessError("detection worker sent a malformed message")
            kind, payload = message
            if kind == "progress":
                if progress_callback is not None:
                    progress_callback(str(payload))
                continue
            if kind == "result":
                process.join(timeout=5.0)
                if process.is_alive():
                    _terminate_process(process)
                return payload
            if kind == "error":
                process.join(timeout=5.0)
                error = payload if isinstance(payload, dict) else {}
                error_type = str(error.get("type") or "DetectionProcessError")
                error_message = str(error.get("message") or "detection worker failed")
                if error_type == "MaterializationError":
                    raise MaterializationError(error_message)
                raise DetectionProcessError(f"{error_type}: {error_message}")
            raise DetectionProcessError(f"unknown detection worker message: {kind!r}")
    finally:
        if process.is_alive():
            _terminate_process(process)
        else:
            process.join(timeout=1.0)
        messages.close()
        messages.cancel_join_thread()


def _detection_worker(messages, kwargs: dict[str, Any]) -> None:
    _apply_gdal_runtime_defaults()

    def progress(text: str) -> None:
        messages.put(("progress", text))

    output_dir = Path(kwargs.get("output_dir") or ".")
    try:
        result = run_detection_for_token(**kwargs, progress_callback=progress)
    except BaseException as exc:  # noqa: BLE001 - child must return a typed failure
        messages.put(("error", _safe_worker_error(exc, output_dir)))
    else:
        messages.put(("result", result))


def _apply_gdal_runtime_defaults() -> dict[str, str]:
    """Apply bounded remote-COG defaults without overriding operator choices."""

    configured = {
        "GDAL_DISABLE_READDIR_ON_OPEN": os.getenv(
            "MARINE_TRACK_GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"
        ),
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": os.getenv(
            "MARINE_TRACK_GDAL_ALLOWED_EXTENSIONS", ".tif,.tiff"
        ),
        "GDAL_HTTP_CONNECTTIMEOUT": os.getenv(
            "MARINE_TRACK_GDAL_HTTP_CONNECT_TIMEOUT_S", "10"
        ),
        "GDAL_HTTP_TIMEOUT": os.getenv("MARINE_TRACK_GDAL_HTTP_TIMEOUT_S", "45"),
        "GDAL_HTTP_LOW_SPEED_LIMIT": os.getenv(
            "MARINE_TRACK_GDAL_HTTP_LOW_SPEED_LIMIT_BPS", "1024"
        ),
        "GDAL_HTTP_LOW_SPEED_TIME": os.getenv(
            "MARINE_TRACK_GDAL_HTTP_LOW_SPEED_TIME_S", "30"
        ),
        "GDAL_HTTP_MAX_RETRY": os.getenv("MARINE_TRACK_GDAL_HTTP_MAX_RETRY", "2"),
        "GDAL_HTTP_RETRY_DELAY": os.getenv(
            "MARINE_TRACK_GDAL_HTTP_RETRY_DELAY_S", "1"
        ),
    }
    applied: dict[str, str] = {}
    for name, value in configured.items():
        if name not in os.environ:
            os.environ[name] = value
        applied[name] = os.environ[name]
    return applied


def _safe_worker_error(exc: BaseException, base_dir: Path) -> dict[str, str]:
    sanitized = redact_value(str(exc), base_dir=base_dir)
    return {
        "type": type(exc).__name__,
        "message": str(sanitized)[:800],
    }


def _terminate_process(process: BaseProcess) -> None:
    if not process.is_alive():
        process.join(timeout=1.0)
        return
    process.terminate()
    process.join(timeout=5.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=5.0)
