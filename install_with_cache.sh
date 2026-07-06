#!/usr/bin/env bash
# Cache-aware install wrapper: provider install + one-time land mask + cleanup.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_NAME="${SERVICE_NAME:-marine-track-bot}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
NO_START=0
EXTRA_ARGS=()

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"

usage() {
  cat <<EOF
Install Marine Track with providers, one-time land-mask preparation and cache cleanup.

Usage:
  ./install_with_cache.sh [options]

Options:
  --providers all|scene|aux|core|none
  --yes
  --no-start
  -h, --help

Land mask is downloaded only when MARINE_TRACK_LAND_MASK_GEOJSON is missing
or MARINE_TRACK_FORCE_UPDATE_LAND_MASK=1 is set.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --providers) PROVIDER_PROFILE="$2"; EXTRA_ARGS+=("$1" "$2"); shift 2 ;;
    --no-start) NO_START=1; EXTRA_ARGS+=("$1"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$SCRIPT_DIR/install_with_providers.sh" --no-start "${EXTRA_ARGS[@]}"

sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" \
  "$VENV_DIR/bin/python" "$INSTALL_DIR/deploy_prepare.py" --env-file "$ENV_FILE"
sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
sudo -u "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/provider_preflight.py"

if [[ "$NO_START" -eq 0 ]]; then
  sudo systemctl enable --now "${SERVICE_NAME}.service"
  sudo systemctl restart "${SERVICE_NAME}.service"
fi

echo "Cache-aware installation complete: profile=$PROVIDER_PROFILE"
