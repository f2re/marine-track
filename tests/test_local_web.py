from __future__ import annotations

import os
from pathlib import Path

import pytest

from marine_track.local_web import (
    LocalWebConfig,
    SearchRequestPayload,
    load_local_env,
    load_local_web_config,
    resolve_output_file,
)


def test_local_config_does_not_require_telegram_token(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("MARINE_TRACK_LOCAL_OUTPUT_DIR", str(tmp_path / "local"))
    monkeypatch.setenv("MARINE_TRACK_LOCAL_PORT", "8091")

    config = load_local_web_config()

    assert config.output_dir == tmp_path / "local"
    assert config.port == 8091
    assert config.host == "127.0.0.1"
    assert config.threshold_sigma == 4.5
    assert config.min_contrast_sigma == 5.0
    assert config.min_area_px == 3


def test_load_local_env_reads_cdse_token_without_overriding_shell(
    monkeypatch, tmp_path: Path
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# provider credentials\nCDSE_ACCESS_TOKEN=file-token\nCDSE_CLIENT_ID='file-client'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CDSE_ACCESS_TOKEN", "shell-token")
    monkeypatch.delenv("CDSE_CLIENT_ID", raising=False)

    loaded = load_local_env(env_path)

    assert loaded == env_path
    assert os.environ["CDSE_ACCESS_TOKEN"] == "shell-token"
    assert os.environ["CDSE_CLIENT_ID"] == "file-client"


def test_search_payload_validates_bbox_and_limits() -> None:
    payload = SearchRequestPayload.from_json(
        {
            "sensor": "sentinel1",
            "hours": 72,
            "max_results": 6,
            "bbox": {"west": 37.45, "south": 44.35, "east": 37.55, "north": 44.45},
        }
    )

    assert payload.sensor.value == "sentinel1"
    assert payload.hours == 72
    assert payload.bbox == (37.45, 44.35, 37.55, 44.45)


@pytest.mark.parametrize(
    "body, message",
    [
        ({}, "bbox"),
        (
            {
                "sensor": "sentinel1",
                "hours": 72,
                "bbox": {"west": 38, "south": 44, "east": 37, "north": 45},
            },
            "bbox",
        ),
        (
            {
                "sensor": "sentinel1",
                "hours": 0,
                "bbox": {"west": 37, "south": 44, "east": 38, "north": 45},
            },
            "hours",
        ),
    ],
)
def test_search_payload_rejects_invalid_input(body: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SearchRequestPayload.from_json(body)


def test_resolve_output_file_blocks_path_traversal(tmp_path: Path) -> None:
    config = LocalWebConfig(output_dir=tmp_path)
    allowed = tmp_path / "detections" / "overview.png"
    allowed.parent.mkdir(parents=True)
    allowed.write_bytes(b"png")

    assert resolve_output_file(config.output_dir, "detections/overview.png") == allowed

    with pytest.raises(ValueError, match="output directory"):
        resolve_output_file(config.output_dir, "../secret.txt")
