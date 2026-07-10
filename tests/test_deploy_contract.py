from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _shell_function(text: str, name: str) -> str:
    marker = f"{name}() {{"
    start = text.index(marker)
    end = text.index("\n}", start) + 2
    return text[start:end]


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


def test_atomic_link_runs_with_bash_nounset(tmp_path: Path):
    text = (ROOT / "deploy_telegram_bot.sh").read_text(encoding="utf-8")
    function = _shell_function(text, "atomic_link")
    target = tmp_path / "release"
    link_path = tmp_path / "current"
    target.mkdir()

    script = f"""set -Eeuo pipefail
{function}
atomic_link {shlex.quote(str(target))} {shlex.quote(str(link_path))}
test -L {shlex.quote(str(link_path))}
test "$(readlink {shlex.quote(str(link_path))})" = {shlex.quote(str(target))}
"""
    subprocess.run(["bash", "-c", script], check=True)


def test_deploy_reconciles_and_safely_loads_canonical_environment():
    text = (ROOT / "deploy_telegram_bot.sh").read_text(encoding="utf-8")
    assert "/etc/marine-track/marine-track.env" in text
    assert "scripts/merge_env_file.py" in text
    assert "--legacy \"$LEGACY_ENV\"" in text
    assert "while IFS= read -r raw || [[ -n \"$raw\" ]]" in text
    assert 'source "$ENV_FILE"' not in text
    assert 'export "$key=$value"' in text


def test_install_reconciles_existing_legacy_and_canonical_environment():
    text = (ROOT / "install_telegram_bot.sh").read_text(encoding="utf-8")
    assert "scripts/merge_env_file.py" in text
    assert "reconciled $LEGACY_ENV with canonical environment file" in text
    assert 'MARINE_TRACK_ENV_FILE="$ENV_FILE"' in text
    assert 'MARINE_TRACK_OUTPUT_DIR=$STATE_DIR/output' in text
    assert 'MARINE_TRACK_CACHE_DIR=$CACHE_DIR' in text


def test_systemd_unit_uses_immutable_current_and_shared_writable_dirs():
    text = (ROOT / "ops" / "marine-track.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=/opt/marine_track/current" in text
    assert "ProtectSystem=strict" in text
    assert "ReadOnlyPaths=/opt/marine_track/releases" in text
    assert "StateDirectory=marine-track" in text
    assert "CacheDirectory=marine-track" in text
    assert "User=marine-track" in text
    assert "Environment=MARINE_TRACK_ENV_FILE=/etc/marine-track/marine-track.env" in text
    assert "EnvironmentFile=/etc/marine-track/marine-track.env" in text



def test_deploy_release_ids_are_retry_safe_and_identity_is_separated():
    deploy = (ROOT / "deploy_telegram_bot.sh").read_text(encoding="utf-8")
    assert 'DEPLOYMENT_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"' in deploy
    assert 'RELEASE_ID="${CODE_VERSION}-${DEPLOYMENT_STAMP}"' in deploy
    assert "-retry${attempt}" in deploy
    assert 'export MARINE_TRACK_CODE_VERSION="$CODE_VERSION"' in deploy
    assert 'export MARINE_TRACK_RELEASE_ID="$RELEASE_ID"' in deploy
    assert '"$STAGING/release.json" "$STAGING/release.env"' in deploy
    assert "release already exists" not in deploy


def test_systemd_loads_release_identity_after_shared_environment():
    unit = (ROOT / "ops" / "marine-track.service").read_text(encoding="utf-8")
    shared = unit.index("EnvironmentFile=/etc/marine-track/marine-track.env")
    release = unit.index("EnvironmentFile=-/opt/marine_track/current/release.env")
    assert shared < release
