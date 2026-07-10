from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"marker not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


deploy = ROOT / "deploy_telegram_bot.sh"
old_release = '''release_source="${MARINE_TRACK_RELEASE_ID:-}"
if [[ -z "$release_source" ]]; then
  release_source="$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
fi
if [[ -z "$release_source" ]]; then
  release_source="$(date -u +%Y%m%dT%H%M%SZ)"
fi
RELEASE_ID="$(printf '%s' "$release_source" | tr -cs 'A-Za-z0-9._-' '-')"
FINAL_RELEASE="$RELEASES_DIR/$RELEASE_ID"
[[ ! -e "$FINAL_RELEASE" ]] || fail "release already exists: $FINAL_RELEASE"
STAGING="$RELEASES_DIR/.staging-$RELEASE_ID-$$"
'''
new_release = '''code_source="${MARINE_TRACK_CODE_VERSION:-${MARINE_TRACK_RELEASE_ID:-}}"
if [[ -z "$code_source" ]]; then
  code_source="$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
fi
if [[ -z "$code_source" ]]; then
  code_source="unknown"
fi
CODE_VERSION="$(printf '%s' "$code_source" | tr -cs 'A-Za-z0-9._-' '-')"
CODE_VERSION="${CODE_VERSION%-}"
[[ -n "$CODE_VERSION" ]] || CODE_VERSION="unknown"
DEPLOYMENT_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RELEASE_ID="${CODE_VERSION}-${DEPLOYMENT_STAMP}"
FINAL_RELEASE="$RELEASES_DIR/$RELEASE_ID"
attempt=1
while [[ -e "$FINAL_RELEASE" || -e "$RELEASES_DIR/.staging-$RELEASE_ID-$$" ]]; do
  RELEASE_ID="${CODE_VERSION}-${DEPLOYMENT_STAMP}-retry${attempt}"
  FINAL_RELEASE="$RELEASES_DIR/$RELEASE_ID"
  attempt=$((attempt + 1))
done
STAGING="$RELEASES_DIR/.staging-$RELEASE_ID-$$"
'''
replace_once(deploy, old_release, new_release)
replace_once(
    deploy,
    'log "staging release $RELEASE_ID"\n',
    'log "staging release $RELEASE_ID (code $CODE_VERSION)"\n',
)
replace_once(
    deploy,
    'export MARINE_TRACK_CODE_VERSION="$RELEASE_ID"\n',
    'export MARINE_TRACK_CODE_VERSION="$CODE_VERSION"\nexport MARINE_TRACK_RELEASE_ID="$RELEASE_ID"\n',
)
metadata_marker = '''if [[ "${EUID}" -eq 0 ]]; then
  chown -R root:root "$STAGING"
fi
chmod -R go-w "$STAGING"
mv "$STAGING" "$FINAL_RELEASE"
'''
metadata_block = '''RELEASE_CREATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$STAGING/.venv/bin/python" - "$STAGING/release.json" "$STAGING/release.env" \
  "$RELEASE_ID" "$CODE_VERSION" "$RELEASE_CREATED_AT" "$profile" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

metadata_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
release_id, code_version, created_at, provider_profile = sys.argv[3:7]
payload = {
    "schema_version": 1,
    "release_id": release_id,
    "code_version": code_version,
    "created_at": created_at,
    "provider_profile": provider_profile,
}
temporary = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\\n", encoding="utf-8")
os.replace(temporary, metadata_path)
env_temporary = env_path.with_suffix(env_path.suffix + ".tmp")
env_temporary.write_text(
    f"MARINE_TRACK_CODE_VERSION={code_version}\\n"
    f"MARINE_TRACK_RELEASE_ID={release_id}\\n",
    encoding="utf-8",
)
os.replace(env_temporary, env_path)
PY

if [[ "${EUID}" -eq 0 ]]; then
  chown -R root:root "$STAGING"
fi
chmod -R go-w "$STAGING"
mv "$STAGING" "$FINAL_RELEASE"
'''
replace_once(deploy, metadata_marker, metadata_block)
replace_once(
    deploy,
    'log "release $RELEASE_ID is active"\n',
    'log "release $RELEASE_ID is active (code $CODE_VERSION)"\n',
)

unit = ROOT / "ops" / "marine-track.service"
replace_once(
    unit,
    "EnvironmentFile=/etc/marine-track/marine-track.env\n",
    "EnvironmentFile=/etc/marine-track/marine-track.env\n"
    "EnvironmentFile=-/opt/marine_track/current/release.env\n",
)

health = ROOT / "src" / "marine_track" / "health.py"
replace_once(
    health,
    "    code_version: str\n    checks: list[HealthCheck]\n",
    "    code_version: str\n    release_id: str\n    checks: list[HealthCheck]\n",
)
replace_once(
    health,
    '            "code_version": self.code_version,\n            "checks": [asdict(check) for check in self.checks],\n',
    '            "code_version": self.code_version,\n'
    '            "release_id": self.release_id,\n'
    '            "checks": [asdict(check) for check in self.checks],\n',
)
replace_once(
    health,
    '        code_version=os.getenv("MARINE_TRACK_CODE_VERSION", "unknown"),\n        checks=checks,\n',
    '        code_version=os.getenv("MARINE_TRACK_CODE_VERSION", "unknown") or "unknown",\n'
    '        release_id=os.getenv("MARINE_TRACK_RELEASE_ID", "unknown") or "unknown",\n'
    '        checks=checks,\n',
)

example = ROOT / ".env.example"
text = example.read_text(encoding="utf-8")
old = "# Optional immutable release identifier when the install tree has no .git metadata.\nMARINE_TRACK_CODE_VERSION=\n"
new = (
    "# Optional code-version override when the source tree has no .git metadata.\n"
    "# Production deploy writes code/release identity into current/release.env.\n"
    "MARINE_TRACK_CODE_VERSION=\n"
    "MARINE_TRACK_RELEASE_ID=\n"
)
if old not in text:
    raise RuntimeError(".env.example code-version marker not found")
example.write_text(text.replace(old, new, 1), encoding="utf-8")

docs = ROOT / "docs" / "DEPLOYMENT.md"
text = docs.read_text(encoding="utf-8")
insert_after = "Failure after the switch restores `previous` and\nrestarts the former release.\n"
addition = '''Failure after the switch restores `previous` and
restarts the former release.

Each attempt uses an immutable directory named `<code-version>-<UTC timestamp>`; therefore a retry of
the same commit never collides with a failed earlier attempt. `release.json` records non-secret
release metadata, while `release.env` supplies `MARINE_TRACK_CODE_VERSION` and
`MARINE_TRACK_RELEASE_ID` to systemd after the shared environment file. Inactive failed attempts are
kept only until normal release retention removes them.
'''
if insert_after not in text:
    raise RuntimeError("deployment documentation marker not found")
docs.write_text(text.replace(insert_after, addition, 1), encoding="utf-8")

test = ROOT / "tests" / "test_deploy_contract.py"
text = test.read_text(encoding="utf-8")
text += '''


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
'''
test.write_text(text, encoding="utf-8")

health_test = ROOT / "tests" / "test_health.py"
text = health_test.read_text(encoding="utf-8")
if "release_id" not in text:
    text += '''


def test_health_report_exposes_release_identity(monkeypatch, tmp_path):
    from marine_track.health import collect_health

    base = tmp_path / "release"
    (base / "config").mkdir(parents=True)
    (base / "data" / "aoi").mkdir(parents=True)
    (base / "config" / "processing.yaml").write_text(
        "ship_detection:\\n  sar:\\n    threshold_sigma: 3.5\\n    min_area_px: 2\\n    max_area_px: 5000\\n    local_window_px: 31\\n    guard_window_px: 5\\n  optical:\\n    threshold_sigma: 3.5\\n    min_area_px: 2\\n    max_area_px: 3000\\n    local_window_px: 31\\n    guard_window_px: 5\\n",
        encoding="utf-8",
    )
    (base / "data" / "aoi" / "example_black_sea.geojson").write_text(
        '{"type":"Polygon","coordinates":[[[30,43],[30.1,43],[30.1,43.1],[30,43.1],[30,43]]]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("MARINE_TRACK_CODE_VERSION", "abc123")
    monkeypatch.setenv("MARINE_TRACK_RELEASE_ID", "abc123-20260710T120000Z")
    monkeypatch.setenv("MARINE_TRACK_OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("MARINE_TRACK_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    report = collect_health(base_dir=base)
    assert report.code_version == "abc123"
    assert report.release_id == "abc123-20260710T120000Z"
    assert report.to_dict()["release_id"] == "abc123-20260710T120000Z"
'''
health_test.write_text(text, encoding="utf-8")

print("retry-safe deployment migration applied")
