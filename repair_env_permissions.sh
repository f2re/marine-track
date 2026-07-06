#!/usr/bin/env bash
# Repair Marine Track .env ownership/mode and run deploy preparation safely.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/marine_track}"
SERVICE_USER="${SERVICE_USER:-marinetrack}"
PROVIDER_PROFILE="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
ENV_FILE="$INSTALL_DIR/.env"
VENV_DIR="$INSTALL_DIR/.venv"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing env file: $ENV_FILE" >&2
  exit 1
fi
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "missing venv python: $VENV_DIR/bin/python" >&2
  exit 1
fi

sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"

sudo env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" \
  "$VENV_DIR/bin/python" "$INSTALL_DIR/deploy_prepare.py" --env-file "$ENV_FILE"

sudo chown root:"$SERVICE_USER" "$ENV_FILE"
sudo chmod 0640 "$ENV_FILE"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR/runs" "$INSTALL_DIR/data/masks" 2>/dev/null || true

echo "Marine Track env permissions repaired and deploy preparation completed."
