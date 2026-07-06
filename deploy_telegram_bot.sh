#!/usr/bin/env bash
# Deploy current checkout to the installed Marine Track Telegram bot directory.

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
  --providers PROFILE      Provider dependencies: all, scene, aux, core, none. Default: all
  --yes
  --install-system-packages
  --skip-pip
  --no-restart
  --status
  -h, --help

Provider profiles:
  all    install core package plus scene and auxiliary provider packages
  scene  install core package plus scene provider packages only
  aux    install core package plus auxiliary provider packages only
  core   install only core package; provider imports are skipped by runtime check
  none   alias for core
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
root_grep_q() { local pattern="$1"; local file="$2"; if [[ -n "$SUDO" ]]; then sudo grep -q "$pattern" "$file"; else grep -q "$pattern" "$file"; fi; }
root_sed_print() { if [[ -n "$SUDO" ]]; then sudo sed "$@"; else sed "$@"; fi; }

confirm() {
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local answer=""
  read -r -p "$1 [Y/n]: " answer
  [[ -z "$answer" || "$answer" =~ ^[YyДд]$ ]]
}

normalize_provider_profile() {
  case "$PROVIDER_PROFILE" in
    all|scene|aux|core) ;;
    none) PROVIDER_PROFILE="core" ;;
    *) fail "invalid provider profile: $PROVIDER_PROFILE. Use all, scene, aux, core, none" ;;
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

git_rev() {
  if git -C "$REPO_ROOT" rev-parse --short HEAD >/dev/null 2>&1; then git -C "$REPO_ROOT" rev-parse --short HEAD; else printf 'unknown'; fi
}

print_status() {
  [[ -d "$REPO_ROOT/.git" ]] && success "source: $REPO_ROOT @ $(git_rev)" || warn "source is not a git checkout: $REPO_ROOT"
  [[ -d "$INSTALL_DIR" ]] && success "install dir: $INSTALL_DIR" || warn "install dir missing: $INSTALL_DIR"
  [[ -f "$ENV_FILE" ]] && success "env file: $ENV_FILE" || warn "env file missing: $ENV_FILE"
  [[ -x "$VENV_DIR/bin/python" ]] && success "venv: $VENV_DIR" || warn "venv missing: $VENV_DIR"
  [[ -f "$UNIT_PATH" ]] && success "systemd unit: $UNIT_PATH" || warn "systemd unit missing: $UNIT_PATH"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
    printf 'active: ' >&2; systemctl is-active "${SERVICE_NAME}.service" >&2 || true
  fi
  [[ -f "$STATE_FILE" ]] && root_sed_print 's/^/state: /' "$STATE_FILE" >&2 || true
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

precheck_source() {
  log "checking source syntax"
  "$PYTHON_BIN" -m compileall -q "$REPO_ROOT/src" "$REPO_ROOT/runtime_check.py" "$REPO_ROOT/register_telegram_commands.py"
  bash -n "$REPO_ROOT/install_telegram_bot.sh"
  bash -n "$REPO_ROOT/deploy_telegram_bot.sh"
}

copy_project() {
  log "syncing $REPO_ROOT -> $INSTALL_DIR"
  run_root rsync -a --delete --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'runs/' --exclude '__pycache__/' --exclude '*.pyc' "$REPO_ROOT/" "$INSTALL_DIR/"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
}

sync_env_defaults() {
  local template="$INSTALL_DIR/.env.example"
  [[ -f "$template" && -f "$ENV_FILE" ]] || return 0
  local added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    local key="${line%%=*}"
    if ! root_grep_q "^${key}=" "$ENV_FILE"; then
      printf '\n%s\n' "$line" | run_root tee -a "$ENV_FILE" >/dev/null
      added=$((added + 1))
    fi
  done < "$template"
  [[ "$added" -gt 0 ]] && warn "added $added missing env keys to $ENV_FILE"
  set_env_key "MARINE_TRACK_PROVIDER_PROFILE" "$PROVIDER_PROFILE"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

set_env_key() {
  local key="$1"
  local value="$2"
  if root_grep_q "^${key}=" "$ENV_FILE"; then
    run_root sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    printf '\n%s=%s\n' "$key" "$value" | run_root tee -a "$ENV_FILE" >/dev/null
  fi
}

ensure_venv_and_deps() {
  local target
  target="$(pip_install_target)"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    run_user "$SERVICE_USER" "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  [[ "$SKIP_PIP" -eq 1 ]] && { warn "pip stage skipped"; return 0; }
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  log "installing python package with provider profile: $PROVIDER_PROFILE ($target)"
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --prefer-binary -e "$target"
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip check
}

runtime_check() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
}

restart_service() {
  [[ "$NO_RESTART" -eq 1 ]] && { warn "restart skipped"; return 0; }
  [[ -f "$UNIT_PATH" ]] || fail "systemd unit missing: $UNIT_PATH"
  run_root systemctl daemon-reload
  run_root systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active --quiet "${SERVICE_NAME}.service" || { run_root journalctl -u "${SERVICE_NAME}.service" -n 80 --no-pager || true; fail "service did not start"; }
}

register_commands() {
  if root_grep_q '^TELEGRAM_BOT_TOKEN=.' "$ENV_FILE"; then
    run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" "$INSTALL_DIR/register_telegram_commands.py" || warn "command registration failed"
  else
    warn "command registration skipped because bot token is empty"
  fi
}

write_state() {
  local installed_at
  installed_at="$({ run_root grep '^installed_at=' "$STATE_FILE" 2>/dev/null || true; } | cut -d= -f2-)"
  cat <<EOF | run_root tee "$STATE_FILE" >/dev/null
installed_at=$installed_at
last_deployed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
source_repo=$REPO_ROOT
source_rev=$(git_rev)
install_dir=$INSTALL_DIR
service_name=$SERVICE_NAME
service_user=$SERVICE_USER
provider_profile=$PROVIDER_PROFILE
venv=$VENV_DIR
unit=$UNIT_PATH
runtime_check=ok
telegram_commands=attempted
EOF
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$STATE_FILE"
}

main() {
  normalize_provider_profile
  print_status
  [[ "$STATUS_ONLY" -eq 1 ]] && exit 0
  require_ready_install
  confirm "Deploy Marine Track bot from $REPO_ROOT to $INSTALL_DIR with provider profile '$PROVIDER_PROFILE'?" || fail "cancelled"
  exec 9>"$DEPLOY_LOCK"
  flock -n 9 || fail "another deploy is running: $DEPLOY_LOCK"
  install_system_packages
  precheck_source
  copy_project
  sync_env_defaults
  ensure_venv_and_deps
  runtime_check
  restart_service
  register_commands
  write_state
  success "deploy complete: $(git_rev)"
}

main "$@"
