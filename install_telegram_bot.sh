#!/usr/bin/env bash
# Install Marine Track Telegram bot. This is the only supported install script.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
SKIP_APT=0
NO_START=0
STATUS_ONLY=0
ASSUME_YES=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
STATE_FILE="$INSTALL_DIR/.install-state"

log() { printf '▶ %s\n' "$*" >&2; }
success() { printf '✓ %s\n' "$*" >&2; }
warn() { printf '! %s\n' "$*" >&2; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }
on_error() {
  local rc=$?
  printf '✗ command failed at line %s with exit %s: %s\n' "$1" "$rc" "$2" >&2
  exit "$rc"
}
trap 'on_error "$LINENO" "$BASH_COMMAND"' ERR

usage() {
  cat <<EOF
Install Marine Track Telegram bot

Usage:
  ./install_telegram_bot.sh [options]

Options:
  --install-dir DIR
  --service-name NAME
  --service-user USER
  --python PATH
  --providers PROFILE      all, scene, aux, core, none. Default: all
  --yes                    Non-interactive; deploy will fail if required values are absent
  --skip-apt
  --no-start
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
    --skip-apt) SKIP_APT=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --status) STATUS_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "unknown option: $1" ;;
  esac
done

ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
STATE_FILE="$INSTALL_DIR/.install-state"
if [[ "$(id -u)" -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi
run_root() { if [[ -n "$SUDO" ]]; then sudo "$@"; else "$@"; fi; }

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
    *) fail "invalid provider profile: $PROVIDER_PROFILE" ;;
  esac
}

print_status() {
  [[ -d "$INSTALL_DIR" ]] && success "install dir: $INSTALL_DIR" || warn "install dir missing: $INSTALL_DIR"
  [[ -x "$VENV_DIR/bin/python" ]] && success "venv: $VENV_DIR" || warn "venv missing: $VENV_DIR"
  [[ -f "$ENV_FILE" ]] && success "env file: $ENV_FILE" || warn "env file missing: $ENV_FILE"
  [[ -f "$UNIT_PATH" ]] && success "systemd unit: $UNIT_PATH" || warn "systemd unit missing: $UNIT_PATH"
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files "${SERVICE_NAME}.service" >/dev/null 2>&1; then
    printf 'active: ' >&2; systemctl is-active "${SERVICE_NAME}.service" >&2 || true
    printf 'enabled: ' >&2; systemctl is-enabled "${SERVICE_NAME}.service" >&2 || true
  fi
  [[ -f "$STATE_FILE" ]] && run_root sed 's/^/state: /' "$STATE_FILE" >&2 || true
}

install_system_packages() {
  [[ "$SKIP_APT" -eq 1 ]] && { warn "apt skipped"; return 0; }
  command -v apt-get >/dev/null 2>&1 || { warn "apt-get not found"; return 0; }
  run_root apt-get update
  run_root apt-get install -y python3 python3-venv python3-pip ca-certificates rsync build-essential python3-dev pkg-config gdal-bin libgdal-dev libproj-dev proj-bin libgeos-dev
}

require_repo_files() {
  [[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "pyproject.toml not found"
  [[ -f "$REPO_ROOT/runtime_check.py" ]] || fail "runtime_check.py not found"
  [[ -f "$REPO_ROOT/deploy_telegram_bot.sh" ]] || fail "deploy_telegram_bot.sh not found"
  [[ -f "$REPO_ROOT/src/marine_track/telegram_bot.py" ]] || fail "telegram bot module not found"
}

ensure_root_access() {
  [[ -z "$SUDO" ]] && return 0
  command -v sudo >/dev/null 2>&1 || fail "root access is required, but sudo is not installed"
  sudo -v || fail "root access is required for install. Run from a real sudo-capable shell or as root."
}

ensure_systemd_available() {
  command -v systemctl >/dev/null 2>&1 || fail "systemctl not found; this installer requires systemd"
  systemctl list-unit-files >/dev/null 2>&1 || fail "systemd is not available from this shell; run install on the host VM with systemd"
}

ensure_user() {
  id "$SERVICE_USER" >/dev/null 2>&1 || run_root useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
}

bootstrap_install_dir() {
  run_root mkdir -p "$INSTALL_DIR"
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
  if [[ ! -f "$ENV_FILE" ]]; then
    run_root install -m 0640 -o root -g "$SERVICE_USER" "$REPO_ROOT/.env.example" "$ENV_FILE"
    warn "created $ENV_FILE"
  fi
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

write_service() {
  cat <<EOF | run_root tee "$UNIT_PATH" >/dev/null
[Unit]
Description=Marine Track Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/python -m marine_track.telegram_bot
Restart=always
RestartSec=10
User=$SERVICE_USER
Group=$SERVICE_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF
  run_root chmod 0644 "$UNIT_PATH"
  run_root systemctl daemon-reload
}

write_initial_state() {
  cat <<EOF | run_root tee "$STATE_FILE" >/dev/null
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
install_dir=$INSTALL_DIR
service_name=$SERVICE_NAME
service_user=$SERVICE_USER
provider_profile=$PROVIDER_PROFILE
venv=$VENV_DIR
unit=$UNIT_PATH
EOF
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$STATE_FILE"
}

run_integrated_deploy() {
  local args=(--install-dir "$INSTALL_DIR" --service-name "$SERVICE_NAME" --service-user "$SERVICE_USER" --python "$PYTHON_BIN" --providers "$PROVIDER_PROFILE")
  [[ "$ASSUME_YES" -eq 1 ]] && args+=(--yes)
  [[ "$NO_START" -eq 1 ]] && args+=(--no-restart)
  "$REPO_ROOT/deploy_telegram_bot.sh" "${args[@]}"
}

main() {
  normalize_provider_profile
  print_status
  [[ "$STATUS_ONLY" -eq 1 ]] && exit 0
  require_repo_files
  confirm "Install Marine Track Telegram bot to $INSTALL_DIR with provider profile '$PROVIDER_PROFILE'?" || fail "cancelled"
  ensure_root_access
  ensure_systemd_available
  install_system_packages
  ensure_user
  bootstrap_install_dir
  write_service
  write_initial_state
  run_integrated_deploy
  success "installation complete"
}

main "$@"
