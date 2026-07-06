#!/usr/bin/env bash
# Provider-aware installation wrapper for Marine Track Telegram bot.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
ASSUME_YES=0
NO_START=0

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"

usage() {
  cat <<EOF
Install Marine Track with provider dependency/profile configuration.

Usage:
  ./install_with_providers.sh [options]

Options:
  --providers all|scene|aux|core|none   Default: all
  --yes                                 Non-interactive; keys are not prompted
  --no-start
  -h, --help

This wrapper:
  1. runs install_telegram_bot.sh with the selected provider profile;
  2. asks provider access keys and paths, unless --yes is used;
  3. installs selected provider extras;
  4. runs runtime_check.py and provider_preflight.py;
  5. starts/restarts the service unless --no-start is used.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --providers) PROVIDER_PROFILE="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    --no-start) NO_START=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

case "$PROVIDER_PROFILE" in
  none) PROVIDER_PROFILE="core" ;;
  all|scene|aux|core) ;;
  *) echo "invalid provider profile: $PROVIDER_PROFILE" >&2; exit 1 ;;
esac

pip_target() {
  case "$PROVIDER_PROFILE" in
    all) printf '%s[providers]' "$INSTALL_DIR" ;;
    scene) printf '%s[scene-providers]' "$INSTALL_DIR" ;;
    aux) printf '%s[aux-providers]' "$INSTALL_DIR" ;;
    core) printf '%s' "$INSTALL_DIR" ;;
  esac
}

if [[ "$ASSUME_YES" -eq 1 ]]; then
  BASE_YES=(--yes)
  CONFIG_YES=(--yes)
else
  BASE_YES=()
  CONFIG_YES=()
fi
if [[ "$NO_START" -eq 1 ]]; then
  BASE_NO_START=(--no-start)
else
  BASE_NO_START=(--no-start)
fi

MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$SCRIPT_DIR/install_telegram_bot.sh" \
  --providers "$PROVIDER_PROFILE" "${BASE_YES[@]}" "${BASE_NO_START[@]}" "${EXTRA_ARGS[@]:-}"

python_args=("$INSTALL_DIR/provider_configure.py" --env-file "$ENV_FILE" --profile "$PROVIDER_PROFILE")
[[ "$ASSUME_YES" -eq 1 ]] && python_args+=(--yes)
sudo "$PYTHON_BIN" "${python_args[@]}"
sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

TARGET="$(pip_target)"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip install --prefer-binary -e "$TARGET"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" -m pip check
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/provider_preflight.py"

if [[ "$NO_START" -eq 0 ]]; then
  sudo systemctl enable --now "${SERVICE_NAME}.service"
  sudo systemctl restart "${SERVICE_NAME}.service"
fi

echo "Provider-aware installation complete: profile=$PROVIDER_PROFILE"
