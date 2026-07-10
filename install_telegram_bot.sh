#!/usr/bin/env bash
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

log() { printf '[marine-track-install] %s
' "$*"; }
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
  DEBIAN_FRONTEND=noninteractive apt-get install -y     python3 python3-venv python3-pip rsync curl ca-certificates util-linux
fi

if ! getent group "$SERVICE_GROUP" >/dev/null; then
  groupadd --system "$SERVICE_GROUP"
fi
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --gid "$SERVICE_GROUP" --home-dir "$STATE_DIR"     --shell /usr/sbin/nologin "$SERVICE_USER"
fi

install -d -o root -g root -m 0755 "$INSTALL_ROOT" "$INSTALL_ROOT/releases"
install -d -o root -g "$SERVICE_GROUP" -m 0750 "$ENV_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_GROUP" -m 0750   "$STATE_DIR" "$STATE_DIR/output" "$CACHE_DIR" /var/log/marine-track

if [[ ! -f "$ENV_FILE" ]]; then
  legacy_env="$INSTALL_ROOT/.env"
  if [[ -f "$legacy_env" ]]; then
    install -o root -g "$SERVICE_GROUP" -m 0640 "$legacy_env" "$ENV_FILE"
    log "migrated legacy environment file"
  else
    install -o root -g "$SERVICE_GROUP" -m 0640 "$PROJECT_ROOT/.env.example" "$ENV_FILE"
    sed -i       -e "s|^MARINE_TRACK_OUTPUT_DIR=.*|MARINE_TRACK_OUTPUT_DIR=$STATE_DIR/output|"       -e "s|^MARINE_TRACK_CACHE_DIR=.*|MARINE_TRACK_CACHE_DIR=$CACHE_DIR|"       "$ENV_FILE"
    log "created $ENV_FILE; set TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_IDS before deploy"
  fi
fi

install -o root -g root -m 0644   "$PROJECT_ROOT/ops/marine-track.service" /etc/systemd/system/marine-track.service
install -o root -g root -m 0644   "$PROJECT_ROOT/ops/tmpfiles.d/marine-track.conf" /etc/tmpfiles.d/marine-track.conf
systemd-tmpfiles --create /etc/tmpfiles.d/marine-track.conf
systemctl daemon-reload
systemctl enable marine-track.service

if [[ "$PREPARE_ONLY" == "1" ]]; then
  log "installation prepared; deployment intentionally skipped"
  exit 0
fi

MARINE_TRACK_ENV_FILE="$ENV_FILE" MARINE_TRACK_INSTALL_ROOT="$INSTALL_ROOT" MARINE_TRACK_STATE_DIR="$STATE_DIR" MARINE_TRACK_CACHE_DIR="$CACHE_DIR" MARINE_TRACK_SERVICE_USER="$SERVICE_USER"   "$PROJECT_ROOT/deploy_telegram_bot.sh"
