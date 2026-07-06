#!/usr/bin/env bash
# Repair Telegram env, validate token and deploy/restart safely.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
ASSUME_YES=0
EXTRA_ARGS=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"

usage() {
  cat <<EOF
Fix Marine Track Telegram deploy.

Usage:
  TELEGRAM_BOT_TOKEN='<bot-token>' ./deploy_fix_telegram.sh --providers all --yes
  ./deploy_fix_telegram.sh --providers all

Options:
  --providers all|scene|aux|core|none
  --yes       Non-interactive; requires TELEGRAM_BOT_TOKEN to be already in env or .env
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --providers) PROVIDER_PROFILE="$2"; EXTRA_ARGS+=("$1" "$2"); shift 2 ;;
    --yes) ASSUME_YES=1; EXTRA_ARGS+=("$1"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE; run install first" >&2; exit 1; }
[[ -x "$VENV_DIR/bin/python" ]] || { echo "missing $VENV_DIR/bin/python; run install first" >&2; exit 1; }

sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

sudo rsync -a "$SCRIPT_DIR/" "$INSTALL_DIR/" \
  --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'runs/' --exclude '__pycache__/' --exclude '*.pyc'
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

telegram_args=("$INSTALL_DIR/telegram_configure.py" --env-file "$ENV_FILE" --require-token)
[[ "$ASSUME_YES" -eq 1 ]] && telegram_args+=(--yes)
sudo env TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}" TELEGRAM_ADMIN_IDS="${TELEGRAM_ADMIN_IDS:-}" \
  "$VENV_DIR/bin/python" "${telegram_args[@]}"
sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --prefer-binary -e "$INSTALL_DIR[providers]"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" "$INSTALL_DIR/telegram_healthcheck.py"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" "$INSTALL_DIR/register_telegram_commands.py"

sudo systemctl daemon-reload
sudo systemctl restart "${SERVICE_NAME}.service"
sleep 2
sudo systemctl is-active --quiet "${SERVICE_NAME}.service"

echo "Telegram deploy fixed and service is active."
