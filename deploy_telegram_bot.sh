#!/usr/bin/env bash
# Deploy Marine Track Telegram bot. This is the only supported deploy script.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
ASSUME_YES=0
NO_RESTART=0
SKIP_PIP=0
STATUS_ONLY=0
INSTALL_SYSTEM_PACKAGES=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
STATE_FILE="$INSTALL_DIR/.install-state"
DEPLOY_LOCK="/tmp/${SERVICE_NAME}.deploy.lock"

log() { printf '▶ %s\n' "$*" >&2; }
success() { printf '✓ %s\n' "$*" >&2; }
warn() { printf '! %s\n' "$*" >&2; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }
on_error() { local rc=$?; printf '✗ command failed at line %s with exit %s: %s\n' "$1" "$rc" "$2" >&2; exit "$rc"; }
trap 'on_error "$LINENO" "$BASH_COMMAND"' ERR

usage() {
  cat <<EOF
Deploy Marine Track Telegram bot

Usage:
  ./deploy_telegram_bot.sh [options]

Options:
  --install-dir DIR
  --service-name NAME
  --service-user USER
  --python PATH
  --providers all|scene|aux|core   Default: all
  --yes                            Non-interactive; requires TELEGRAM_BOT_TOKEN in environment or .env
  --install-system-packages
  --skip-pip
  --no-restart
  --status
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --service-user) SERVICE_USER="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
    --providers) PROVIDER_PROFILE="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --install-system-packages) INSTALL_SYSTEM_PACKAGES=1; shift ;;
    --skip-pip) SKIP_PIP=1; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    --status) STATUS_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
STATE_FILE="$INSTALL_DIR/.install-state"
DEPLOY_LOCK="/tmp/${SERVICE_NAME}.deploy.lock"
if [[ "$(id -u)" -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi
run_root() { if [[ -n "$SUDO" ]]; then sudo "$@"; else "$@"; fi; }
run_user() { local user="$1"; shift; if [[ -n "$SUDO" ]]; then sudo -u "$user" "$@"; else runuser -u "$user" -- "$@"; fi; }

confirm() {
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local answer=""
  read -r -p "$1 [Y/n]: " answer
  [[ -z "$answer" || "$answer" =~ ^[YyДд]$ ]]
}

normalize_provider_profile() {
  case "$PROVIDER_PROFILE" in
    all|scene|aux|core) ;;
    *) fail "invalid provider profile: $PROVIDER_PROFILE. Use all, scene, aux, core" ;;
  esac
}

pip_install_target() {
  case "$PROVIDER_PROFILE" in
    all) printf '%s[providers]' "$INSTALL_DIR" ;;
    scene) printf '%s[scene-providers]' "$INSTALL_DIR" ;;
    aux) printf '%s[aux-providers]' "$INSTALL_DIR" ;;
    core) printf '%s' "$INSTALL_DIR" ;;
  esac
}

git_rev() { git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || printf 'unknown'; }

print_status() {
  [[ -d "$REPO_ROOT/.git" ]] && success "source: $REPO_ROOT @ $(git_rev)" || warn "source is not a git checkout: $REPO_ROOT"
  [[ -d "$INSTALL_DIR" ]] && success "install dir: $INSTALL_DIR" || warn "install dir missing: $INSTALL_DIR"
  [[ -f "$ENV_FILE" ]] && success "env file: $ENV_FILE" || warn "env file missing: $ENV_FILE"
  [[ -x "$VENV_DIR/bin/python" ]] && success "venv: $VENV_DIR" || warn "venv missing: $VENV_DIR"
  [[ -f "$UNIT_PATH" ]] && success "systemd unit: $UNIT_PATH" || warn "systemd unit missing: $UNIT_PATH"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
    printf 'active: ' >&2; systemctl is-active "${SERVICE_NAME}.service" >&2 || true
  fi
  [[ -f "$STATE_FILE" ]] && run_root sed 's/^/state: /' "$STATE_FILE" >&2 || true
}

ensure_root_access() {
  [[ -z "$SUDO" ]] && return 0
  command -v sudo >/dev/null 2>&1 || fail "root access is required, but sudo is not installed"
  sudo -v || fail "root access is required for deploy"
}

require_ready_install() {
  [[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "pyproject.toml not found in source"
  [[ -f "$REPO_ROOT/runtime_check.py" ]] || fail "runtime_check.py not found in source"
  [[ -f "$REPO_ROOT/src/marine_track/telegram_bot.py" ]] || fail "telegram bot module not found in source"
  [[ -d "$INSTALL_DIR" ]] || fail "$INSTALL_DIR does not exist; run install_telegram_bot.sh first"
  [[ -f "$ENV_FILE" ]] || fail "$ENV_FILE does not exist; run install_telegram_bot.sh first"
  id "$SERVICE_USER" >/dev/null 2>&1 || fail "service user not found: $SERVICE_USER"
}

install_system_packages() {
  [[ "$INSTALL_SYSTEM_PACKAGES" -eq 1 ]] || return 0
  command -v apt-get >/dev/null 2>&1 || { warn "apt-get not found"; return 0; }
  run_root apt-get update
  run_root apt-get install -y python3 python3-venv python3-pip ca-certificates rsync build-essential python3-dev pkg-config gdal-bin libgdal-dev libproj-dev proj-bin libgeos-dev
}

copy_project() {
  log "syncing $REPO_ROOT -> $INSTALL_DIR"
  run_root rsync -a --delete --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'runs/' --exclude 'data/masks/land.geojson' --exclude 'data/masks/cache/' --exclude '__pycache__/' --exclude '*.pyc' "$REPO_ROOT/" "$INSTALL_DIR/"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

env_tool() {
  run_root "$PYTHON_BIN" - "$ENV_FILE" "$@" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1]); op = sys.argv[2]; key = sys.argv[3]
if op == "get":
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw and not raw.lstrip().startswith("#") and "=" in raw and raw.split("=", 1)[0].strip() == key:
                print(raw.split("=", 1)[1].strip().strip('"').strip("'"))
                break
elif op == "exists":
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw and not raw.lstrip().startswith("#") and "=" in raw and raw.split("=", 1)[0].strip() == key:
                raise SystemExit(0)
    raise SystemExit(1)
elif op == "set":
    value = sys.argv[4]
    lines = []; seen = False
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw and not raw.lstrip().startswith("#") and "=" in raw and raw.split("=", 1)[0].strip() == key:
                lines.append(f"{key}={value}"); seen = True
            else:
                lines.append(raw)
    if not seen:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
else:
    raise SystemExit(f"unknown env op: {op}")
PY
}

env_get() { env_tool get "$1"; }
env_set() { env_tool set "$1" "$2"; }
env_key_exists() { env_tool exists "$1"; }
env_has_value() { [[ -n "$(env_get "$1")" ]]; }

sync_env_defaults() {
  local template="$INSTALL_DIR/.env.example"
  [[ -f "$template" && -f "$ENV_FILE" ]] || return 0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    local key="${line%%=*}"
    env_key_exists "$key" || printf '\n%s\n' "$line" | run_root tee -a "$ENV_FILE" >/dev/null
  done < "$template"
  env_set MARINE_TRACK_PROVIDER_PROFILE "$PROVIDER_PROFILE"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

configure_telegram_access() {
  [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] && env_set TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN"
  [[ -n "${TELEGRAM_ADMIN_IDS:-}" ]] && env_set TELEGRAM_ADMIN_IDS "$TELEGRAM_ADMIN_IDS"
  if ! env_has_value TELEGRAM_BOT_TOKEN && [[ "$ASSUME_YES" -eq 0 ]]; then
    local value=""
    read -r -s -p "Telegram bot token from BotFather [TELEGRAM_BOT_TOKEN]: " value
    printf '\n' >&2
    [[ -n "$value" ]] && env_set TELEGRAM_BOT_TOKEN "$value"
  fi
  env_has_value TELEGRAM_BOT_TOKEN || fail "TELEGRAM_BOT_TOKEN is empty. Set it in $ENV_FILE before deploy."
}

ensure_venv_and_deps() {
  local target; target="$(pip_install_target)"
  [[ -x "$VENV_DIR/bin/python" ]] || run_user "$SERVICE_USER" "$PYTHON_BIN" -m venv "$VENV_DIR"
  [[ "$SKIP_PIP" -eq 1 ]] && { warn "pip stage skipped"; return 0; }
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --prefer-binary -e "$target"
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip check
}

project_path() { local raw="$1"; [[ "$raw" = /* ]] && printf '%s' "$raw" || printf '%s/%s' "$INSTALL_DIR" "$raw"; }

ensure_runtime_dirs() {
  local output_dir cache_dir noaa_cache mask_value mask_dir
  output_dir="$(env_get MARINE_TRACK_OUTPUT_DIR)"; [[ -z "$output_dir" ]] && output_dir="runs/telegram"
  cache_dir="$(env_get MARINE_TRACK_CACHE_DIR)"; [[ -z "$cache_dir" ]] && cache_dir="runs/cache"
  noaa_cache="$(env_get NOAA_MARINECADASTRE_CACHE_DIR)"; [[ -z "$noaa_cache" ]] && noaa_cache="runs/noaa_ais"
  mask_value="$(env_get MARINE_TRACK_LAND_MASK_GEOJSON)"
  [[ -n "$mask_value" ]] && mask_dir="$(dirname "$(project_path "$mask_value")")" || mask_dir="$INSTALL_DIR/data/masks"
  run_root mkdir -p "$(project_path "$output_dir")" "$(project_path "$cache_dir")" "$(project_path "$noaa_cache")" "$mask_dir"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$(project_path "$output_dir")" "$(project_path "$cache_dir")" "$(project_path "$noaa_cache")" "$mask_dir"
}

prepare_land_mask_once() {
  local auto force mask source cache_dir aoi
  auto="$(env_get MARINE_TRACK_AUTO_UPDATE_LAND_MASK)"; [[ -z "$auto" ]] && auto="1"
  [[ "$auto" =~ ^(1|true|yes|on)$ ]] || return 0
  mask="$(env_get MARINE_TRACK_LAND_MASK_GEOJSON)"; [[ -z "$mask" ]] && mask="$INSTALL_DIR/data/masks/land.geojson" && env_set MARINE_TRACK_LAND_MASK_GEOJSON "$mask"
  mask="$(project_path "$mask")"
  force="$(env_get MARINE_TRACK_FORCE_UPDATE_LAND_MASK)"; [[ -z "$force" ]] && force="0"
  [[ -f "$mask" && "$force" != "1" && "$force" != "true" ]] && { success "land mask exists, download skipped: $mask"; return 0; }
  source="$(env_get MARINE_TRACK_LAND_MASK_SOURCE_URL)"; [[ -z "$source" ]] && source="https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
  cache_dir="$(env_get MARINE_TRACK_LAND_MASK_CACHE_DIR)"; [[ -z "$cache_dir" ]] && cache_dir="data/masks/cache"; cache_dir="$(project_path "$cache_dir")"
  aoi="$(env_get MARINE_TRACK_DEFAULT_AOI)"; [[ -z "$aoi" ]] && aoi="data/aoi/example_black_sea.geojson"; aoi="$(project_path "$aoi")"
  run_root mkdir -p "$(dirname "$mask")" "$cache_dir"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$(dirname "$mask")" "$cache_dir"
  local args=(update-land-mask --output "$mask" --source "$source" --cache-dir "$cache_dir" --force)
  [[ -f "$aoi" ]] && args+=(--aoi "$aoi")
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/marine-track" "${args[@]}" || warn "land mask update failed; continuing without land mask"
}

runtime_check() { run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"; }
provider_preflight() { run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" -m marine_track.provider_preflight --env-file "$ENV_FILE"; }

telegram_getme_check() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
import json, os, sys
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    raise SystemExit("Telegram healthcheck failed: TELEGRAM_BOT_TOKEN is empty")
try:
    with urlopen("https://api.telegram.org/" + "bot" + token + "/getMe", timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
except HTTPError as exc:
    raise SystemExit(f"Telegram healthcheck failed: HTTP {exc.code}; token is probably invalid") from exc
except URLError as exc:
    raise SystemExit(f"Telegram healthcheck failed: network error: {exc}") from exc
if not payload.get("ok"):
    raise SystemExit(f"Telegram healthcheck failed: {payload}")
print("Telegram healthcheck OK")
PY
}

register_commands() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
import asyncio, os, sys
from telegram import Bot
from marine_track.telegram_commands import BOT_COMMANDS
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    raise SystemExit("command registration failed: TELEGRAM_BOT_TOKEN is empty")
async def main() -> None:
    await Bot(token).set_my_commands(list(BOT_COMMANDS))
asyncio.run(main())
print("Telegram commands registered")
PY
}

cleanup_runtime_files() { run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/marine-track" cleanup-cache || warn "cleanup failed"; }

restart_service() {
  [[ "$NO_RESTART" -eq 1 ]] && { warn "restart skipped"; return 0; }
  command -v systemctl >/dev/null 2>&1 || fail "systemctl not found"
  run_root systemctl daemon-reload
  run_root systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active --quiet "${SERVICE_NAME}.service" || { run_root journalctl -u "${SERVICE_NAME}.service" -n 80 --no-pager || true; fail "service did not start"; }
}

write_state() {
  cat <<EOF | run_root tee "$STATE_FILE" >/dev/null
last_deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
source_repo=$REPO_ROOT
source_rev=$(git_rev)
install_dir=$INSTALL_DIR
service_name=$SERVICE_NAME
service_user=$SERVICE_USER
provider_profile=$PROVIDER_PROFILE
runtime_check=ok
provider_preflight=ok
telegram_getme=ok
telegram_commands=registered
EOF
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$STATE_FILE"
}

main() {
  normalize_provider_profile
  print_status
  [[ "$STATUS_ONLY" -eq 1 ]] && exit 0
  require_ready_install
  confirm "Deploy Marine Track bot from $REPO_ROOT to $INSTALL_DIR with provider profile '$PROVIDER_PROFILE'?" || fail "cancelled"
  ensure_root_access
  exec 9>"$DEPLOY_LOCK"
  flock -n 9 || fail "another deploy is running: $DEPLOY_LOCK"
  install_system_packages
  "$PYTHON_BIN" -m compileall -q "$REPO_ROOT/src" "$REPO_ROOT/runtime_check.py"
  bash -n "$REPO_ROOT/install_telegram_bot.sh"
  bash -n "$REPO_ROOT/deploy_telegram_bot.sh"
  copy_project
  sync_env_defaults
  configure_telegram_access
  ensure_venv_and_deps
  ensure_runtime_dirs
  prepare_land_mask_once
  cleanup_runtime_files
  runtime_check
  provider_preflight
  telegram_getme_check
  register_commands
  restart_service
  write_state
  success "deploy complete: $(git_rev)"
}

main "$@"
