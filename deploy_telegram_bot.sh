#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${MARINE_TRACK_SOURCE_DIR:-$PROJECT_ROOT}"
INSTALL_ROOT="${MARINE_TRACK_INSTALL_ROOT:-/opt/marine_track}"
RELEASES_DIR="$INSTALL_ROOT/releases"
CURRENT_LINK="$INSTALL_ROOT/current"
PREVIOUS_LINK="$INSTALL_ROOT/previous"
ENV_FILE="${MARINE_TRACK_ENV_FILE:-/etc/marine-track/marine-track.env}"
ENV_TEMPLATE="${MARINE_TRACK_ENV_TEMPLATE:-$SOURCE_DIR/.env.example}"
ENV_MERGER="${MARINE_TRACK_ENV_MERGER:-$PROJECT_ROOT/scripts/merge_env_file.py}"
LEGACY_ENV="$INSTALL_ROOT/.env"
STATE_DIR="${MARINE_TRACK_STATE_DIR:-/var/lib/marine-track}"
CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-/var/cache/marine-track}"
SERVICE_NAME="${MARINE_TRACK_SERVICE_NAME:-marine-track.service}"
SERVICE_USER="${MARINE_TRACK_SERVICE_USER:-marine-track}"
SERVICE_GROUP="${MARINE_TRACK_SERVICE_GROUP:-marine-track}"
LOCK_FILE="${MARINE_TRACK_DEPLOY_LOCK:-/run/lock/marine-track-deploy.lock}"
KEEP_RELEASES="${MARINE_TRACK_KEEP_RELEASES:-5}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SWITCHED=0
OLD_RELEASE=""
STAGING=""

log() { printf '[marine-track-deploy] %s\n' "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

load_env_file() {
  local path="$1" raw line key value first last
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    raw="${raw%$'\r'}"
    line="$(trim "$raw")"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == *=* ]] || fail "invalid environment line in $path"
    key="$(trim "${line%%=*}")"
    value="$(trim "${line#*=}")"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail "invalid environment key in $path: $key"
    if (( ${#value} >= 2 )); then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ ( "$first" == '"' && "$last" == '"' ) || ( "$first" == "'" && "$last" == "'" ) ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    export "$key=$value"
  done < "$path"
}

sync_environment() {
  [[ -f "$ENV_TEMPLATE" ]] || fail "environment template not found: $ENV_TEMPLATE"
  [[ -f "$ENV_MERGER" ]] || fail "environment merger not found: $ENV_MERGER"
  mkdir -p "$(dirname "$ENV_FILE")"

  local args=(
    --template "$ENV_TEMPLATE"
    --target "$ENV_FILE"
    --set "MARINE_TRACK_ENV_FILE=$ENV_FILE"
    --set "MARINE_TRACK_OUTPUT_DIR=$STATE_DIR/output"
    --set "MARINE_TRACK_CACHE_DIR=$CACHE_DIR"
  )
  if [[ -f "$LEGACY_ENV" && "$LEGACY_ENV" != "$ENV_FILE" ]]; then
    args+=(--legacy "$LEGACY_ENV")
  fi
  "$PYTHON_BIN" "$ENV_MERGER" "${args[@]}"
  if [[ "${EUID}" -eq 0 ]]; then
    chown root:"$SERVICE_GROUP" "$ENV_FILE"
    chmod 0640 "$ENV_FILE"
  fi
}

if [[ "${EUID}" -ne 0 && "${MARINE_TRACK_ALLOW_NON_ROOT_DEPLOY:-0}" != "1" ]]; then
  fail "run as root (or set MARINE_TRACK_ALLOW_NON_ROOT_DEPLOY=1 for an isolated test root)"
fi

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another deployment is already running"

sync_environment
[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"
load_env_file "$ENV_FILE"
export MARINE_TRACK_ENV_FILE="$ENV_FILE"

[[ -n "${TELEGRAM_BOT_TOKEN:-}" ]] || fail "TELEGRAM_BOT_TOKEN is empty in $ENV_FILE"

export MARINE_TRACK_OUTPUT_DIR="${MARINE_TRACK_OUTPUT_DIR:-$STATE_DIR/output}"
export MARINE_TRACK_CACHE_DIR="${MARINE_TRACK_CACHE_DIR:-$CACHE_DIR}"
mkdir -p "$RELEASES_DIR" "$MARINE_TRACK_OUTPUT_DIR" "$MARINE_TRACK_CACHE_DIR"
if [[ "${EUID}" -eq 0 ]]; then
  chown -R "$SERVICE_USER:$SERVICE_GROUP" "$STATE_DIR" "$CACHE_DIR"
fi

release_source="${MARINE_TRACK_RELEASE_ID:-}"
if [[ -z "$release_source" ]]; then
  release_source="$(git -C "$SOURCE_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"
fi
if [[ -z "$release_source" ]]; then
  release_source="$(date -u +%Y%m%dT%H%M%SZ)"
fi
RELEASE_ID="$(printf '%s' "$release_source" | tr -cs 'A-Za-z0-9._-' '-')"
FINAL_RELEASE="$RELEASES_DIR/$RELEASE_ID"
[[ ! -e "$FINAL_RELEASE" ]] || fail "release already exists: $FINAL_RELEASE"
STAGING="$RELEASES_DIR/.staging-$RELEASE_ID-$$"

cleanup_staging() {
  [[ -z "$STAGING" || ! -e "$STAGING" ]] || rm -rf "$STAGING"
}

atomic_link() {
  local target="$1" link="$2" temporary="${link}.new.$$"
  ln -s "$target" "$temporary"
  mv -Tf "$temporary" "$link"
}

rollback() {
  local status="$?"
  if [[ "$SWITCHED" == "1" ]]; then
    log "post-switch validation failed; rolling back"
    if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
      atomic_link "$OLD_RELEASE" "$CURRENT_LINK"
      systemctl restart "$SERVICE_NAME" || true
    else
      rm -f "$CURRENT_LINK"
      systemctl stop "$SERVICE_NAME" || true
    fi
  fi
  cleanup_staging
  exit "$status"
}
trap rollback ERR
trap cleanup_staging EXIT

log "staging release $RELEASE_ID"
mkdir -p "$STAGING"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'runs/' \
  --exclude '__pycache__/' \
  "$SOURCE_DIR/" "$STAGING/"

"$PYTHON_BIN" -m venv "$STAGING/.venv"
"$STAGING/.venv/bin/python" -m pip install --upgrade pip wheel
profile="${MARINE_TRACK_PROVIDER_PROFILE:-all}"
case "$profile" in
  all) package_spec="$STAGING[providers]" ;;
  scene) package_spec="$STAGING[scene-providers]" ;;
  aux) package_spec="$STAGING[aux-providers]" ;;
  core) package_spec="$STAGING" ;;
  *) fail "invalid MARINE_TRACK_PROVIDER_PROFILE=$profile" ;;
esac
"$STAGING/.venv/bin/pip" install "$package_spec"

export MARINE_TRACK_CODE_VERSION="$RELEASE_ID"
"$STAGING/.venv/bin/python" -m compileall -q "$STAGING/src" "$STAGING/runtime_check.py"
"$STAGING/.venv/bin/python" "$STAGING/runtime_check.py"
"$STAGING/.venv/bin/python" -m marine_track.smoke_check \
  --base-dir "$STAGING" --env-file "$ENV_FILE"
"$STAGING/.venv/bin/python" -m marine_track.health \
  --base-dir "$STAGING" --env-file "$ENV_FILE" --json

if [[ "${EUID}" -eq 0 ]]; then
  chown -R root:root "$STAGING"
fi
chmod -R go-w "$STAGING"
mv "$STAGING" "$FINAL_RELEASE"
STAGING=""

if [[ -L "$CURRENT_LINK" ]]; then
  OLD_RELEASE="$(readlink -f "$CURRENT_LINK")"
fi
if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
  atomic_link "$OLD_RELEASE" "$PREVIOUS_LINK"
fi
atomic_link "$FINAL_RELEASE" "$CURRENT_LINK"
SWITCHED=1

systemctl daemon-reload
systemctl restart "$SERVICE_NAME"
systemctl is-active --quiet "$SERVICE_NAME"
"$CURRENT_LINK/.venv/bin/python" -m marine_track.health \
  --base-dir "$CURRENT_LINK" --env-file "$ENV_FILE" --telegram --json

SWITCHED=0
trap - ERR
log "release $RELEASE_ID is active"

mapfile -t releases < <(
  find "$RELEASES_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '.staging-*' -printf '%T@ %p\n' \
    | sort -nr \
    | awk '{print $2}'
)
current_real="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
previous_real="$(readlink -f "$PREVIOUS_LINK" 2>/dev/null || true)"
kept=0
for release in "${releases[@]}"; do
  if [[ "$release" == "$current_real" || "$release" == "$previous_real" ]]; then
    continue
  fi
  kept=$((kept + 1))
  if (( kept > KEEP_RELEASES )); then
    rm -rf "$release"
  fi
done
