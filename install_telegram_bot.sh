#!/usr/bin/env bash
# Install Marine Track Telegram bot into /opt and run it as a systemd service.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
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
  --yes
  --skip-apt
  --no-start
  --status
  -h, --help

Before start, put bot credentials into .env or export them in environment.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --service-user) SERVICE_USER="$2"; shift 2 ;;
    --python) PYTHON_BIN="$2"; shift 2 ;;
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
run_user() { local user="$1"; shift; if [[ -n "$SUDO" ]]; then sudo -u "$user" "$@"; else runuser -u "$user" -- "$@"; fi; }

confirm() {
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local answer=""
  read -r -p "$1 [Y/n]: " answer
  [[ -z "$answer" || "$answer" =~ ^[YyДд]$ ]]
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
  [[ -f "$STATE_FILE" ]] && sed 's/^/state: /' "$STATE_FILE" >&2 || true
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
  [[ -f "$REPO_ROOT/register_telegram_commands.py" ]] || fail "register_telegram_commands.py not found"
  [[ -f "$REPO_ROOT/src/marine_track/telegram_bot.py" ]] || fail "telegram bot module not found"
}

ensure_user() {
  id "$SERVICE_USER" >/dev/null 2>&1 || run_root useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
}

copy_project() {
  run_root mkdir -p "$INSTALL_DIR"
  run_root rsync -a --delete --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'runs/' --exclude '__pycache__/' --exclude '*.pyc' "$REPO_ROOT/" "$INSTALL_DIR/"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
}

write_env_if_missing() {
  if [[ ! -f "$ENV_FILE" ]]; then
    run_root install -m 0640 -o root -g "$SERVICE_USER" "$INSTALL_DIR/.env.example" "$ENV_FILE"
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
      run_root sed -i "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}|" "$ENV_FILE"
    fi
    if [[ -n "${TELEGRAM_ADMIN_IDS:-}" ]]; then
      run_root sed -i "s|^TELEGRAM_ADMIN_IDS=.*|TELEGRAM_ADMIN_IDS=${TELEGRAM_ADMIN_IDS}|" "$ENV_FILE"
    fi
    warn "created $ENV_FILE; edit it before starting if credentials are empty"
  fi
  sync_env_defaults
}

sync_env_defaults() {
  local template="$INSTALL_DIR/.env.example"
  [[ -f "$template" && -f "$ENV_FILE" ]] || return 0
  local added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    local key="${line%%=*}"
    if ! grep -q "^${key}=" "$ENV_FILE"; then
      printf '\n%s\n' "$line" | run_root tee -a "$ENV_FILE" >/dev/null
      added=$((added + 1))
    fi
  done < "$template"
  [[ "$added" -gt 0 ]] && warn "added $added missing env keys to $ENV_FILE"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

create_venv() {
  run_user "$SERVICE_USER" "$PYTHON_BIN" -m venv "$VENV_DIR"
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --prefer-binary -e "$INSTALL_DIR"
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip check
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

start_service() {
  [[ "$NO_START" -eq 1 ]] && { warn "service not started"; return 0; }
  if ! grep -q '^TELEGRAM_BOT_TOKEN=.' "$ENV_FILE"; then
    warn "bot token is empty in $ENV_FILE; service start skipped"
    return 0
  fi
  run_root systemctl enable --now "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active --quiet "${SERVICE_NAME}.service" || { run_root journalctl -u "${SERVICE_NAME}.service" -n 60 --no-pager || true; fail "service did not start"; }
}

write_state() {
  cat <<EOF | run_root tee "$STATE_FILE" >/dev/null
installed_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
install_dir=$INSTALL_DIR
service_name=$SERVICE_NAME
service_user=$SERVICE_USER
venv=$VENV_DIR
unit=$UNIT_PATH
EOF
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$STATE_FILE"
}

main() {
  print_status
  [[ "$STATUS_ONLY" -eq 1 ]] && exit 0
  require_repo_files
  confirm "Install Marine Track Telegram bot to $INSTALL_DIR?" || fail "cancelled"
  install_system_packages
  ensure_user
  copy_project
  write_env_if_missing
  create_venv
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
  write_service
  start_service
  write_state
  success "installation complete"
}

main "$@"
