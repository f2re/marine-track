from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/marine_track/health.py",
    '''from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


@dataclass(frozen=True)
class HealthCheck:
    name: str
    status: str
    critical: bool
    detail: str
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class HealthReport:
    status: str
    generated_at: str
    hostname: str
    package_version: str
    code_version: str
    checks: list[HealthCheck]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "generated_at": self.generated_at,
            "hostname": self.hostname,
            "package_version": self.package_version,
            "code_version": self.code_version,
            "checks": [asdict(check) for check in self.checks],
        }


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def collect_health(
    *,
    base_dir: Path | None = None,
    env_file: Path | None = None,
    check_telegram: bool = False,
) -> HealthReport:
    base_dir = (base_dir or Path.cwd()).resolve()
    if env_file is not None:
        load_env_file(env_file)

    checks: list[HealthCheck] = []
    processing_path = _resolve_path(
        os.getenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml"),
        base_dir,
    )
    checks.append(_processing_config_check(processing_path))

    default_aoi = _resolve_path(
        os.getenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi/example_black_sea.geojson"),
        base_dir,
    )
    checks.append(
        HealthCheck(
            name="default_aoi",
            status="ok" if default_aoi.is_file() else "failed",
            critical=True,
            detail="available" if default_aoi.is_file() else f"missing: {default_aoi.name}",
        )
    )

    output_dir = _resolve_path(
        os.getenv("MARINE_TRACK_OUTPUT_DIR", "runs/telegram"),
        base_dir,
    )
    cache_dir = _resolve_path(
        os.getenv("MARINE_TRACK_CACHE_DIR", "runs/cache"),
        base_dir,
    )
    checks.append(_writable_check("output_dir", output_dir))
    checks.append(_writable_check("cache_dir", cache_dir))
    checks.append(_disk_check(output_dir))
    checks.append(_registry_check(output_dir / "scene_registry.json"))
    checks.append(_calibration_check(output_dir))
    checks.append(_access_policy_check())

    if check_telegram:
        checks.append(_telegram_check())

    critical_failed = any(check.critical and check.status == "failed" for check in checks)
    degraded = any(check.status in {"warning", "failed"} for check in checks)
    status = "failed" if critical_failed else "degraded" if degraded else "ok"
    return HealthReport(
        status=status,
        generated_at=datetime.now(timezone.utc).isoformat(),
        hostname=socket.gethostname(),
        package_version=_package_version(),
        code_version=os.getenv("MARINE_TRACK_CODE_VERSION", "unknown"),
        checks=checks,
    )


def _processing_config_check(path: Path) -> HealthCheck:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("root is not an object")
        detection = payload.get("ship_detection")
        if not isinstance(detection, dict):
            raise ValueError("ship_detection is missing")
        for section in ("sar", "optical"):
            config = detection.get(section)
            if not isinstance(config, dict):
                raise ValueError(f"ship_detection.{section} is missing")
            for name in (
                "threshold_sigma",
                "min_area_px",
                "max_area_px",
                "local_window_px",
                "guard_window_px",
            ):
                if name not in config:
                    raise ValueError(f"ship_detection.{section}.{name} is missing")
        return HealthCheck(
            name="processing_config",
            status="ok",
            critical=True,
            detail="validated",
            data={"path": path.name},
        )
    except Exception as exc:
        return HealthCheck(
            name="processing_config",
            status="failed",
            critical=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _writable_check(name: str, path: Path) -> HealthCheck:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as file_obj:
            file_obj.write(b"ok")
            file_obj.flush()
        return HealthCheck(name=name, status="ok", critical=True, detail="writable")
    except Exception as exc:
        return HealthCheck(
            name=name,
            status="failed",
            critical=True,
            detail=f"not writable: {type(exc).__name__}",
        )


def _disk_check(path: Path) -> HealthCheck:
    try:
        free = shutil.disk_usage(path).free
        minimum_mb = int(os.getenv("MARINE_TRACK_HEALTH_MIN_FREE_MB", "512"))
        free_mb = free // (1024 * 1024)
        status = "ok" if free_mb >= minimum_mb else "failed"
        return HealthCheck(
            name="disk_free",
            status=status,
            critical=True,
            detail=f"{free_mb} MiB free; minimum {minimum_mb} MiB",
            data={"free_mb": free_mb, "minimum_mb": minimum_mb},
        )
    except Exception as exc:
        return HealthCheck(
            name="disk_free",
            status="failed",
            critical=True,
            detail=f"{type(exc).__name__}: {exc}",
        )


def _registry_check(path: Path) -> HealthCheck:
    if not path.is_file():
        return HealthCheck(
            name="scene_registry",
            status="warning",
            critical=False,
            detail="not created yet",
            data={"records": 0},
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("registry root is not an object")
        unscoped = [
            token
            for token, record in payload.items()
            if not isinstance(record, dict)
            or not isinstance(record.get("owner_user_id"), int)
            or not isinstance(record.get("owner_chat_id"), int)
        ]
        if unscoped:
            return HealthCheck(
                name="scene_registry",
                status="warning",
                critical=False,
                detail="legacy/unscoped records are ignored",
                data={"records": len(payload), "unscoped": len(unscoped)},
            )
        return HealthCheck(
            name="scene_registry",
            status="ok",
            critical=False,
            detail="valid and scoped",
            data={"records": len(payload), "unscoped": 0},
        )
    except Exception as exc:
        return HealthCheck(
            name="scene_registry",
            status="failed",
            critical=True,
            detail=f"invalid JSON/state: {type(exc).__name__}",
        )


def _calibration_check(output_dir: Path) -> HealthCheck:
    candidate = output_dir / "calibration" / "profile.json"
    active_profiles = list(output_dir.glob("**/active_profile.json"))
    files = ([candidate] if candidate.is_file() else []) + active_profiles
    if not files:
        return HealthCheck(
            name="calibration_profiles",
            status="warning",
            critical=False,
            detail="no active profile yet; baseline ranking remains in use",
            data={"profiles": 0},
        )
    invalid = 0
    active = 0
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                invalid += 1
                continue
            if payload.get("active") or path.name == "active_profile.json":
                active += 1
        except Exception:
            invalid += 1
    if invalid:
        return HealthCheck(
            name="calibration_profiles",
            status="failed",
            critical=True,
            detail="one or more profile files are invalid",
            data={"profiles": len(files), "invalid": invalid, "active": active},
        )
    return HealthCheck(
        name="calibration_profiles",
        status="ok" if active else "warning",
        critical=False,
        detail="active profile available" if active else "profiles exist but none is active",
        data={"profiles": len(files), "invalid": 0, "active": active},
    )


def _access_policy_check() -> HealthCheck:
    admin_ids = _parse_ids(os.getenv("TELEGRAM_ADMIN_IDS", ""))
    public = _env_bool(os.getenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "0"))
    if public is None:
        return HealthCheck(
            name="telegram_access_policy",
            status="failed",
            critical=True,
            detail="MARINE_TRACK_ALLOW_PUBLIC_BOT is not boolean",
        )
    if not admin_ids and not public:
        return HealthCheck(
            name="telegram_access_policy",
            status="failed",
            critical=True,
            detail="fail-closed: configure TELEGRAM_ADMIN_IDS or explicit public mode",
        )
    return HealthCheck(
        name="telegram_access_policy",
        status="ok",
        critical=True,
        detail="public explicit" if public else "administrator allowlist",
        data={"administrator_count": len(admin_ids), "public": public},
    )


def _telegram_check() -> HealthCheck:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return HealthCheck(
            name="telegram_get_me",
            status="failed",
            critical=True,
            detail="TELEGRAM_BOT_TOKEN is empty",
        )
    request = Request(
        f"https://api.telegram.org/bot{token}/getMe",
        headers={"User-Agent": "marine-track-health/0.1"},
    )
    try:
        with urlopen(request, timeout=15) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        result = payload.get("result") if isinstance(payload, dict) else None
        if not payload.get("ok") or not isinstance(result, dict):
            raise ValueError("Telegram returned ok=false")
        return HealthCheck(
            name="telegram_get_me",
            status="ok",
            critical=True,
            detail="Telegram API reachable and token accepted",
            data={"bot_id": result.get("id"), "username": result.get("username")},
        )
    except HTTPError as exc:
        detail = f"Telegram HTTP {exc.code}"
    except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        detail = f"Telegram check failed: {type(exc).__name__}"
    return HealthCheck(
        name="telegram_get_me",
        status="failed",
        critical=True,
        detail=detail,
    )


def _parse_ids(value: str) -> set[int]:
    output: set[int] = set()
    for part in value.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            output.add(int(part))
        except ValueError:
            return set()
    return output


def _env_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    return None


def _resolve_path(raw: str, base_dir: Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else base_dir / path


def _package_version() -> str:
    try:
        return version("marine-track")
    except PackageNotFoundError:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marine Track runtime health report")
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--env-file")
    parser.add_argument("--telegram", action="store_true", help="Call Telegram getMe")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    report = collect_health(
        base_dir=Path(args.base_dir),
        env_file=Path(args.env_file) if args.env_file else None,
        check_telegram=args.telegram,
    )
    if args.as_json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Marine Track health: {report.status}")
        for check in report.checks:
            marker = "OK" if check.status == "ok" else "WARN" if check.status == "warning" else "FAIL"
            print(f"[{marker}] {check.name}: {check.detail}")
    return 1 if report.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
)


write(
    "ops/marine-track.service",
    '''[Unit]
Description=Marine Track Telegram Bot
After=network-online.target
Wants=network-online.target
ConditionPathIsDirectory=/opt/marine_track/current

[Service]
Type=simple
User=marine-track
Group=marine-track
EnvironmentFile=/etc/marine-track/marine-track.env
WorkingDirectory=/opt/marine_track/current
ExecStartPre=/opt/marine_track/current/.venv/bin/python /opt/marine_track/current/runtime_check.py
ExecStart=/opt/marine_track/current/.venv/bin/marine-track-bot
Restart=on-failure
RestartSec=10
TimeoutStartSec=180
TimeoutStopSec=45
KillSignal=SIGINT
UMask=0027

StateDirectory=marine-track
CacheDirectory=marine-track
LogsDirectory=marine-track
ReadWritePaths=/var/lib/marine-track /var/cache/marine-track /var/log/marine-track
ReadOnlyPaths=/opt/marine_track/releases
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
ProtectClock=true
ProtectHostname=true
LockPersonality=true
RestrictSUIDSGID=true
RestrictRealtime=true
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
''',
)


write(
    "ops/tmpfiles.d/marine-track.conf",
    '''d /var/lib/marine-track 0750 marine-track marine-track -
d /var/lib/marine-track/output 0750 marine-track marine-track -
d /var/cache/marine-track 0750 marine-track marine-track -
d /var/log/marine-track 0750 marine-track marine-track -
d /opt/marine_track 0755 root root -
d /opt/marine_track/releases 0755 root root -
''',
)


write(
    "deploy_telegram_bot.sh",
    '''#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${MARINE_TRACK_SOURCE_DIR:-$PROJECT_ROOT}"
INSTALL_ROOT="${MARINE_TRACK_INSTALL_ROOT:-/opt/marine_track}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
PREVIOUS_LINK="$INSTALL_ROOT/previous"
ENV_FILE="${MARINE_TRACK_ENV_FILE:-/etc/marine-track/marine-track.env}"
STATE_DIR="${MARINE_TRACK_STATE_DIR:-/var/lib/marine-track}"
CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-/var/cache/marine-track}"
SERVICE_NAME="${MARINE_TRACK_SERVICE_NAME:-marine-track.service}"
SERVICE_USER="${MARINE_TRACK_SERVICE_USER:-marine-track}"
LOCK_FILE="${MARINE_TRACK_DEPLOY_LOCK:-/run/lock/marine-track-deploy.lock}"
KEEP_RELEASES="${MARINE_TRACK_KEEP_RELEASES:-5}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SWITCHED=0
OLD_RELEASE=""
STAGING=""

log() { printf '[marine-track-deploy] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 && "${MARINE_TRACK_ALLOW_NON_ROOT_DEPLOY:-0}" != "1" ]]; then
  fail "run as root (or set MARINE_TRACK_ALLOW_NON_ROOT_DEPLOY=1 for an isolated test root)"
fi

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another deployment is already running"

[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export MARINE_TRACK_OUTPUT_DIR="${MARINE_TRACK_OUTPUT_DIR:-$STATE_DIR/output}"
export MARINE_TRACK_CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-$CACHE_DIR}"
mkdir -p "$RELEASES_DIR" "$MARINE_TRACK_OUTPUT_DIR" "$MARINE_TRACK_CACHE_DIR"
if [[ "${EUID}" -eq 0 ]]; then
  chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR" "$CACHE_DIR"
fi

release_source="${MARINE_TRACK_RELEASE_ID:-}"
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

cleanup_staging() {
  [[ -z "$STAGING" || ! -e "$STAGING" ]] || rm -rf "$STAGING"
}

atomic_link() {
  local target="$1" link="$2" temporary="${link}.new.$$"
  ln -s "$target" "$temporary"
  mv -Tf "$temporary" "$link"
}

rollback() {
  local status="$?"
  if [[ "$SWITCHED" == "1" ]]; then
    log "post-switch validation failed; rolling back"
    if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
      atomic_link "$OLD_RELEASE" "$CURRENT_LINK"
      systemctl restart "$SERVICE_NAME" || true
    else
      rm -f "$CURRENT_LINK"
      systemctl stop "$SERVICE_NAME" || true
    fi
  fi
  cleanup_staging
  exit "$status"
}
trap rollback ERR
trap cleanup_staging EXIT

log "staging release $RELEASE_ID"
mkdir -p "$STAGING"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'runs/' \
  --exclude '__pycache__/' \
  "$SOURCE_DIR/" "$STAGING/"

"$PYTHON_BIN" -m venv "$STAGING/.venv"
"$STAGING/.venv/bin/python" -m pip install --upgrade pip wheel
profile="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
case "$profile" in
  all) package_spec="$STAGING[providers]" ;;
  scene) package_spec="$STAGING[scene-providers]" ;;
  aux) package_spec="$STAGING[aux-providers]" ;;
  core) package_spec="$STAGING" ;;
  *) fail "invalid MARINE_TRACK_PROVIDER_PROFILE=$profile" ;;
esac
"$STAGING/.venv/bin/pip" install "$package_spec"

export MARINE_TRACK_CODE_VERSION="$RELEASE_ID"
"$STAGING/.venv/bin/python" -m compileall -q "$STAGING/src" "$STAGING/runtime_check.py"
"$STAGING/.venv/bin/python" "$STAGING/runtime_check.py"
"$STAGING/.venv/bin/python" -m marine_track.smoke_check \
  --base-dir "$STAGING" --env-file "$ENV_FILE"
"$STAGING/.venv/bin/python" -m marine_track.health \
  --base-dir "$STAGING" --env-file "$ENV_FILE" --json

if [[ "${EUID}" -eq 0 ]]; then
  chown -R root:root "$STAGING"
fi
chmod -R go-w "$STAGING"
mv "$STAGING" "$FINAL_RELEASE"
STAGING=""

if [[ -L "$CURRENT_LINK" ]]; then
  OLD_RELEASE="$(readlink -f "$CURRENT_LINK")"
fi
if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
  atomic_link "$OLD_RELEASE" "$PREVIOUS_LINK"
fi
atomic_link "$FINAL_RELEASE" "$CURRENT_LINK"
SWITCHED=1

systemctl daemon-reload
systemctl restart "$SERVICE_NAME"
systemctl is-active --quiet "$SERVICE_NAME"
"$CURRENT_LINK/.venv/bin/python" -m marine_track.health \
  --base-dir "$CURRENT_LINK" --env-file "$ENV_FILE" --telegram --json

SWITCHED=0
trap - ERR
log "release $RELEASE_ID is active"

mapfile -t releases < <(find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '.staging-*' -printf '%T@ %p\n' | sort -nr | awk '{print $2}')
current_real="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
previous_real="$(readlink -f "$PREVIOUS_LINK" 2>/dev/null || true)"
kept=0
for release in "${releases[@]}"; do
  if [[ "$release" == "$current_real" || "$release" == "$previous_real" ]]; then
    continue
  fi
  kept=$((kept + 1))
  if (( kept > KEEP_RELEASES )); then
    rm -rf "$release"
  fi
done
''',
)


write(
    "install_telegram_bot.sh",
    '''#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${MARINE_TRACK_INSTALL_ROOT:-/opt/marine_track}"
ENV_DIR="${MARINE_TRACK_ENV_DIR:-/etc/marine-track}"
ENV_FILE="${MARINE_TRACK_ENV_FILE:-$ENV_DIR/marine-track.env}"
SERVICE_USER="${MARINE_TRACK_SERVICE_USER:-marine-track}"
SERVICE_GROUP="${MARINE_TRACK_SERVICE_GROUP:-marine-track}"
STATE_DIR="${MARINE_TRACK_STATE_DIR:-/var/lib/marine-track}"
CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-/var/cache/marine-track}"
PREPARE_ONLY=0

log() { printf '[marine-track-install] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

for argument in "$@"; do
  case "$argument" in
    --prepare-only) PREPARE_ONLY=1 ;;
    *) fail "unknown argument: $argument" ;;
  esac
done

[[ "$EUID" -eq 0 ]] || fail "run as root"

if [[ "${MARINE_TRACK_SKIP_APT:-0}" != "1" ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3 python3-venv python3-pip rsync curl ca-certificates util-linux
fi

if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" --home-dir "$STATE_DIR" \
    --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 "$INSTALL_ROOT" "$INSTALL_ROOT/releases"
install -d -o root -g "$SERVICE_GROUP" -m 0750 "$ENV_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750 \
  "$STATE_DIR" "$STATE_DIR/output" "$CACHE_DIR" /var/log/marine-track

if [[ ! -f "$ENV_FILE" ]]; then
  legacy_env="$INSTALL_ROOT/.env"
  if [[ -f "$legacy_env" ]]; then
    install -o root -g "$SERVICE_GROUP" -m 0640 "$legacy_env" "$ENV_FILE"
    log "migrated legacy environment file"
  else
    install -o root -g "$SERVICE_GROUP" -m 0640 "$PROJECT_ROOT/.env.example" "$ENV_FILE"
    sed -i \
      -e "s|^MARINE_TRACK_OUTPUT_DIR=.*|MARINE_TRACK_OUTPUT_DIR=$STATE_DIR/output|" \
      -e "s|^MARINE_TRACK_CACHE_DIR=.*|MARINE_TRACK_CACHE_DIR=$CACHE_DIR|" \
      "$ENV_FILE"
    log "created $ENV_FILE; set TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_IDS before deploy"
  fi
fi

install -o root -g root -m 0644 \
  "$PROJECT_ROOT/ops/marine-track.service" /etc/systemd/system/marine-track.service
install -o root -g root -m 0644 \
  "$PROJECT_ROOT/ops/tmpfiles.d/marine-track.conf" /etc/tmpfiles.d/marine-track.conf
systemd-tmpfiles --create /etc/tmpfiles.d/marine-track.conf
systemctl daemon-reload
systemctl enable marine-track.service

if [[ "$PREPARE_ONLY" == "1" ]]; then
  log "installation prepared; deployment intentionally skipped"
  exit 0
fi

MARINE_TRACK_ENV_FILE="$ENV_FILE" \
MARINE_TRACK_INSTALL_ROOT="$INSTALL_ROOT" \
MARINE_TRACK_STATE_DIR="$STATE_DIR" \
MARINE_TRACK_CACHE_DIR="$CACHE_DIR" \
MARINE_TRACK_SERVICE_USER="$SERVICE_USER" \
  "$PROJECT_ROOT/deploy_telegram_bot.sh"
''',
)


write(
    "docs/DEPLOYMENT.md",
    '''# Atomic production deployment

The production layout separates immutable releases from mutable runtime state:

```text
/opt/marine_track/releases/<release-id>/   root-owned code and venv
/opt/marine_track/current -> releases/...  atomic active symlink
/opt/marine_track/previous -> releases/... rollback target
/etc/marine-track/marine-track.env          root:marine-track 0640
/var/lib/marine-track/output/               service-owned state/output
/var/cache/marine-track/                    service-owned provider/raster cache
/var/log/marine-track/                      service-owned logs
```

Initial preparation:

```bash
sudo ./install_telegram_bot.sh --prepare-only
sudoedit /etc/marine-track/marine-track.env
sudo ./deploy_telegram_bot.sh
```

A deploy holds `/run/lock/marine-track-deploy.lock`, copies the source into a
staging release, builds a non-editable virtual environment, runs compile,
`runtime_check.py`, smoke check and offline health check, makes the release
read-only, switches `current` atomically, restarts systemd and executes an online
Telegram `getMe` health gate. Failure after the switch restores `previous` and
restarts the former release.

Use the health command independently:

```bash
/opt/marine_track/current/.venv/bin/marine-track-health \
  --base-dir /opt/marine_track/current \
  --env-file /etc/marine-track/marine-track.env \
  --telegram --json
```

`degraded` is non-fatal and normally means that no scene registry or calibrated
profile exists yet. `failed` exits non-zero and blocks deploy/start. Set
`MARINE_TRACK_HEALTH_MIN_FREE_MB` to the required free-space floor and
`MARINE_TRACK_KEEP_RELEASES` to the number of non-current/non-previous releases
to retain.
''',
)


write(
    "tests/test_health.py",
    '''from __future__ import annotations

import json
from pathlib import Path

from marine_track.health import collect_health


def write_processing(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """ship_detection:
  sar:
    threshold_sigma: 3.5
    min_area_px: 2
    max_area_px: 5000
    local_window_px: 31
    guard_window_px: 5
  optical:
    threshold_sigma: 3.5
    min_area_px: 2
    max_area_px: 3000
    local_window_px: 31
    guard_window_px: 5
""",
        encoding="utf-8",
    )


def configure(tmp_path, monkeypatch):
    write_processing(tmp_path / "config" / "processing.yaml")
    aoi = tmp_path / "data" / "aoi.geojson"
    aoi.parent.mkdir(parents=True)
    aoi.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
    monkeypatch.setenv("MARINE_TRACK_PROCESSING_CONFIG", "config/processing.yaml")
    monkeypatch.setenv("MARINE_TRACK_DEFAULT_AOI", "data/aoi.geojson")
    monkeypatch.setenv("MARINE_TRACK_OUTPUT_DIR", "state/output")
    monkeypatch.setenv("MARINE_TRACK_CACHE_DIR", "state/cache")
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123")
    monkeypatch.setenv("MARINE_TRACK_ALLOW_PUBLIC_BOT", "0")
    monkeypatch.setenv("MARINE_TRACK_HEALTH_MIN_FREE_MB", "1")


def test_health_is_degraded_but_non_failed_before_first_calibration(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    report = collect_health(base_dir=tmp_path)
    assert report.status == "degraded"
    assert not any(check.critical and check.status == "failed" for check in report.checks)
    serialized = json.dumps(report.to_dict())
    assert "TELEGRAM_BOT_TOKEN" not in serialized


def test_corrupt_registry_is_critical(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    registry = tmp_path / "state" / "output" / "scene_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{broken", encoding="utf-8")
    report = collect_health(base_dir=tmp_path)
    assert report.status == "failed"
    check = next(item for item in report.checks if item.name == "scene_registry")
    assert check.critical is True


def test_scoped_registry_is_accepted(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    registry = tmp_path / "state" / "output" / "scene_registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"token": {"owner_user_id": 123, "owner_chat_id": 456}}),
        encoding="utf-8",
    )
    report = collect_health(base_dir=tmp_path)
    check = next(item for item in report.checks if item.name == "scene_registry")
    assert check.status == "ok"


def test_fail_closed_access_policy_is_health_failure(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch)
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "")
    report = collect_health(base_dir=tmp_path)
    assert report.status == "failed"
''',
)


write(
    "tests/test_deploy_contract.py",
    '''from __future__ import annotations

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
''',
)


# Add a dedicated health entry point without changing the existing Telegram script.
pyproject = ROOT / "pyproject.toml"
text = pyproject.read_text(encoding="utf-8")
marker = 'marine-track-bot = "marine_track.telegram_bot:main"\n'
if 'marine-track-health = "marine_track.health:main"' not in text:
    if marker not in text:
        raise RuntimeError("pyproject script marker not found")
    text = text.replace(marker, marker + 'marine-track-health = "marine_track.health:main"\n', 1)
pyproject.write_text(text, encoding="utf-8")

# Runtime import coverage.
runtime = ROOT / "runtime_check.py"
text = runtime.read_text(encoding="utf-8")
marker = '    "marine_track.telegram_bot",\n'
if '    "marine_track.health",\n' not in text:
    if marker not in text:
        raise RuntimeError("runtime module marker not found")
    text = text.replace(marker, marker + '    "marine_track.health",\n', 1)
runtime.write_text(text, encoding="utf-8")

# Shell syntax is a release gate, not only a Python unit test.
workflow = ROOT / ".github" / "workflows" / "ci.yml"
text = workflow.read_text(encoding="utf-8")
marker = "      - name: Compile\n        run: python -m compileall -q src runtime_check.py\n"
addition = marker + "      - name: Shell syntax\n        run: bash -n install_telegram_bot.sh deploy_telegram_bot.sh\n"
if "      - name: Shell syntax\n" not in text:
    if marker not in text:
        raise RuntimeError("CI compile marker not found")
    text = text.replace(marker, addition, 1)
workflow.write_text(text, encoding="utf-8")

# Runtime defaults for the separated writable directories/health floor.
env = ROOT / ".env.example"
text = env.read_text(encoding="utf-8")
if "MARINE_TRACK_HEALTH_MIN_FREE_MB=" not in text:
    text += "\n# Runtime health/deployment\nMARINE_TRACK_HEALTH_MIN_FREE_MB=512\nMARINE_TRACK_KEEP_RELEASES=5\n"
env.write_text(text, encoding="utf-8")

print("atomic release and health migration applied")
