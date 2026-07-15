#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_ROOT="${MARINE_TRACK_INSTALL_ROOT:-/opt/marine_track}"
ENV_DIR="${MARINE_TRACK_ENV_DIR:-/etc/marine-track}"
ENV_FILE="${MARINE_TRACK_ENV_FILE:-$ENV_DIR/marine-track.env}"
ENV_TEMPLATE="${MARINE_TRACK_ENV_TEMPLATE:-$PROJECT_ROOT/.env.example}"
ENV_MERGER="${MARINE_TRACK_ENV_MERGER:-$PROJECT_ROOT/scripts/merge_env_file.py}"
LEGACY_ENV="$INSTALL_ROOT/.env"
SERVICE_USER="${MARINE_TRACK_SERVICE_USER:-marine-track}"
SERVICE_GROUP="${MARINE_TRACK_SERVICE_GROUP:-marine-track}"
STATE_DIR="${MARINE_TRACK_STATE_DIR:-/var/lib/marine-track}"
CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-/var/cache/marine-track}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PREPARE_ONLY=0

log() { printf '[marine-track-install] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

print_onboarding() {
  log "administrator guide: https://github.com/f2re/marine-track#quick-start"
  log "create Telegram bot/token: https://t.me/BotFather"
  log "minimal credentials: TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_IDS"
  log "Sentinel-1 uses tokenless Planetary Computer by default"
  log "optional provider registration links are documented in README and $ENV_FILE"
}

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

[[ -f "$ENV_TEMPLATE" ]] || fail "environment template not found: $ENV_TEMPLATE"
[[ -f "$ENV_MERGER" ]] || fail "environment merger not found: $ENV_MERGER"

env_existed=0
[[ -f "$ENV_FILE" ]] && env_existed=1
merge_args=(
  --template "$ENV_TEMPLATE"
  --target "$ENV_FILE"
  --set "MARINE_TRACK_ENV_FILE=$ENV_FILE"
  --set "MARINE_TRACK_OUTPUT_DIR=$STATE_DIR/output"
  --set "MARINE_TRACK_CACHE_DIR=$CACHE_DIR"
)
if [[ -f "$LEGACY_ENV" && "$LEGACY_ENV" != "$ENV_FILE" ]]; then
  merge_args+=(--legacy "$LEGACY_ENV")
fi
"$PYTHON_BIN" "$ENV_MERGER" "${merge_args[@]}"
chown root:"$SERVICE_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

if [[ "$env_existed" == "0" && -f "$LEGACY_ENV" ]]; then
  log "migrated non-empty legacy values from $LEGACY_ENV"
elif [[ -f "$LEGACY_ENV" ]]; then
  log "reconciled $LEGACY_ENV with canonical environment file"
fi
log "canonical environment file: $ENV_FILE"
log "provider secrets are optional and are not requested interactively"
print_onboarding

install -o root -g root -m 0644 \
  "$PROJECT_ROOT/ops/marine-track.service" /etc/systemd/system/marine-track.service
install -o root -g root -m 0644 \
  "$PROJECT_ROOT/ops/tmpfiles.d/marine-track.conf" /etc/tmpfiles.d/marine-track.conf
systemd-tmpfiles --create /etc/tmpfiles.d/marine-track.conf
systemctl daemon-reload
systemctl enable marine-track.service

if [[ "$PREPARE_ONLY" == "1" ]]; then
  log "installation prepared"
  log "next: sudoedit $ENV_FILE"
  log "then: sudo bash $PROJECT_ROOT/deploy_telegram_bot.sh"
  exit 0
fi

MARINE_TRACK_ENV_FILE="$ENV_FILE" \
MARINE_TRACK_INSTALL_ROOT="$INSTALL_ROOT" \
MARINE_TRACK_STATE_DIR="$STATE_DIR" \
MARINE_TRACK_CACHE_DIR="$CACHE_DIR" \
MARINE_TRACK_SERVICE_USER="$SERVICE_USER" \
MARINE_TRACK_SERVICE_GROUP="$SERVICE_GROUP" \
  "$PROJECT_ROOT/deploy_telegram_bot.sh"
