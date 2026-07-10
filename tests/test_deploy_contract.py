from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shell_scripts_are_syntactically_valid():
    for name in ("install_telegram_bot.sh", "deploy_telegram_bot.sh"):
        subprocess.run(["bash", "-n", str(ROOT / name)], check=True)


def test_deploy_is_atomic_non_editable_and_has_rollback():
    text = (ROOT / "deploy_telegram_bot.sh").read_text(encoding="utf-8")
    assert "flock -n" in text
    assert "mv -Tf" in text
    assert "rollback" in text
    assert "pip install -e" not in text
    assert "systemctl is-active --quiet" in text
    assert "-m marine_track.health" in text
    assert ".staging-" in text


def test_systemd_unit_uses_immutable_current_and_shared_writable_dirs():
    text = (ROOT / "ops" / "marine-track.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/opt/marine_track/current" in text
    assert "ProtectSystem=strict" in text
    assert "ReadOnlyPaths=/opt/marine_track/releases" in text
    assert "StateDirectory=marine-track" in text
    assert "CacheDirectory=marine-track" in text
    assert "User=marine-track" in text
