from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import runtime_check

ROOT = Path(__file__).resolve().parents[1]
MERGER = ROOT / "scripts" / "merge_env_file.py"


def run_merger(
    template: Path,
    target: Path,
    legacy: Path | None = None,
    overrides: dict[str, str] | None = None,
) -> None:
    command = [
        sys.executable,
        str(MERGER),
        "--template",
        str(template),
        "--target",
        str(target),
    ]
    if legacy is not None:
        command.extend(["--legacy", str(legacy)])
    for key, value in (overrides or {}).items():
        command.extend(["--set", f"{key}={value}"])
    subprocess.run(command, check=True, capture_output=True, text=True)


def test_merger_fills_empty_canonical_values_from_legacy_and_normalizes(tmp_path: Path):
    template = tmp_path / ".env.example"
    template.write_text(
        "# Telegram bot\n"
        "TELEGRAM_BOT_TOKEN=\n"
        "TELEGRAM_ADMIN_IDS=\n"
        "MARINE_TRACK_ALLOW_PUBLIC_BOT=0\n"
        "\n"
        "# Optional overrides\n"
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA=\n"
        "MARINE_TRACK_OUTPUT_DIR=runs/telegram\n"
        "MARINE_TRACK_CACHE_DIR=runs/cache\n",
        encoding="utf-8",
    )
    target = tmp_path / "marine-track.env"
    target.write_text(
        "TELEGRAM_BOT_TOKEN=\n\n"
        "TELEGRAM_ADMIN_IDS=\n\n"
        "CUSTOM_CANONICAL=kept",
        encoding="utf-8",
    )
    legacy = tmp_path / ".env"
    legacy.write_text(
        "TELEGRAM_BOT_TOKEN=legacy-token\n"
        "TELEGRAM_ADMIN_IDS=12345\n"
        "CUSTOM_LEGACY=migrated",
        encoding="utf-8",
    )

    run_merger(
        template,
        target,
        legacy,
        {
            "MARINE_TRACK_ENV_FILE": str(target),
            "MARINE_TRACK_OUTPUT_DIR": "/var/lib/marine-track/output",
            "MARINE_TRACK_CACHE_DIR": "/var/cache/marine-track",
        },
    )

    text = target.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN=legacy-token\n" in text
    assert "TELEGRAM_ADMIN_IDS=12345\n" in text
    assert "CUSTOM_CANONICAL=kept\n" in text
    assert "CUSTOM_LEGACY=migrated\n" in text
    assert "MARINE_TRACK_OUTPUT_DIR=/var/lib/marine-track/output\n" in text
    assert "MARINE_TRACK_CACHE_DIR=/var/cache/marine-track\n" in text
    assert text.count("TELEGRAM_BOT_TOKEN=") == 1
    assert text.count("TELEGRAM_ADMIN_IDS=") == 1
    assert "TELEGRAM_BOT_TOKEN=legacy-token\n\nTELEGRAM_ADMIN_IDS" not in text
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_nonempty_canonical_secret_wins_over_legacy(tmp_path: Path):
    template = tmp_path / ".env.example"
    template.write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    target = tmp_path / "marine-track.env"
    target.write_text("TELEGRAM_BOT_TOKEN=canonical-token", encoding="utf-8")
    legacy = tmp_path / ".env"
    legacy.write_text("TELEGRAM_BOT_TOKEN=legacy-token", encoding="utf-8")

    run_merger(template, target, legacy)

    assert target.read_text(encoding="utf-8") == "TELEGRAM_BOT_TOKEN=canonical-token\n"


def test_runtime_check_treats_blank_numeric_overrides_as_unset():
    blank_overrides = {
        "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA": "",
        "MARINE_TRACK_DETECTION_MIN_AREA_PX": "",
        "MARINE_TRACK_DETECTION_MAX_AREA_PX": "",
        "MARINE_TRACK_DETECTION_LOCAL_WINDOW_PX": "",
        "MARINE_TRACK_DETECTION_GUARD_WINDOW_PX": "",
        "MARINE_TRACK_DETECTION_MIN_CONTRAST_SIGMA": "",
    }
    with patch.dict(os.environ, blank_overrides, clear=True):
        assert runtime_check.check_numeric_env() == []

    with patch.dict(
        os.environ,
        {"MARINE_TRACK_DETECTION_THRESHOLD_SIGMA": "not-a-number"},
        clear=True,
    ):
        assert runtime_check.check_numeric_env() == [
            "MARINE_TRACK_DETECTION_THRESHOLD_SIGMA must be numeric, got 'not-a-number'"
        ]


def test_runtime_check_loads_canonical_file_over_empty_process_value(tmp_path: Path):
    env_file = tmp_path / "marine-track.env"
    env_file.write_text("TELEGRAM_BOT_TOKEN=file-token", encoding="utf-8")

    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=True):
        runtime_check.load_dotenv(env_file)
        assert os.environ["TELEGRAM_BOT_TOKEN"] == "file-token"
