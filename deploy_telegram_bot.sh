#!/usr/bin/env bash
# Deploy Marine Track Telegram bot. This is the only supported deploy script.

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
on_error() {
  local rc=$?
  printf '✗ command failed at line %s with exit %s: %s\n' "$1" "$rc" "$2" >&2
  exit "$rc"
}
trap 'on_error "$LINENO" "$BASH_COMMAND"' ERR

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
  --yes                    Non-interactive; requires TELEGRAM_BOT_TOKEN to be already in env or .env
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

enable_scene_providers() { [[ "$PROVIDER_PROFILE" == "all" || "$PROVIDER_PROFILE" == "scene" ]]; }
enable_aux_providers() { [[ "$PROVIDER_PROFILE" == "all" || "$PROVIDER_PROFILE" == "aux" ]]; }

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
  if [[ -f "$STATE_FILE" ]]; then
    run_root sed 's/^/state: /' "$STATE_FILE" >&2 || true
  fi
}

require_ready_install() {
  [[ -f "$REPO_ROOT/pyproject.toml" ]] || fail "pyproject.toml not found in source"
  [[ -f "$REPO_ROOT/runtime_check.py" ]] || fail "runtime_check.py not found in source"
  [[ -f "$REPO_ROOT/src/marine_track/telegram_bot.py" ]] || fail "telegram bot module not found in source"
  [[ -d "$INSTALL_DIR" ]] || fail "$INSTALL_DIR does not exist; run install_telegram_bot.sh first"
  [[ -f "$ENV_FILE" ]] || fail "$ENV_FILE does not exist; run install_telegram_bot.sh first"
  id "$SERVICE_USER" >/dev/null 2>&1 || fail "service user not found: $SERVICE_USER"
}

ensure_root_access() {
  [[ -z "$SUDO" ]] && return 0
  command -v sudo >/dev/null 2>&1 || fail "root access is required, but sudo is not installed"
  sudo -v || fail "root access is required for deploy. Run from a real sudo-capable shell or as root."
}

ensure_systemd_available() {
  [[ "$NO_RESTART" -eq 1 ]] && return 0
  command -v systemctl >/dev/null 2>&1 || fail "systemctl not found; this deploy script requires systemd"
  systemctl list-unit-files >/dev/null 2>&1 || fail "systemd is not available from this shell; run deploy on the host VM with systemd, or use --no-restart only for file sync"
}

install_system_packages() {
  [[ "$INSTALL_SYSTEM_PACKAGES" -eq 1 ]] || return 0
  command -v apt-get >/dev/null 2>&1 || { warn "apt-get not found"; return 0; }
  run_root apt-get update
  run_root apt-get install -y python3 python3-venv python3-pip ca-certificates rsync build-essential python3-dev pkg-config gdal-bin libgdal-dev libproj-dev proj-bin libgeos-dev
}

precheck_source() {
  log "checking source syntax"
  "$PYTHON_BIN" -m compileall -q "$REPO_ROOT/src" "$REPO_ROOT/runtime_check.py"
  bash -n "$REPO_ROOT/install_telegram_bot.sh"
  bash -n "$REPO_ROOT/deploy_telegram_bot.sh"
}

copy_project() {
  log "syncing $REPO_ROOT -> $INSTALL_DIR"
  run_root rsync -a --delete --exclude '.git/' --exclude '.venv/' --exclude '.env' --exclude 'runs/' --exclude '__pycache__/' --exclude '*.pyc' "$REPO_ROOT/" "$INSTALL_DIR/"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

env_key_exists() {
  local key="$1"
  run_root "$PYTHON_BIN" - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
for raw in path.read_text(encoding="utf-8").splitlines():
    if raw.split("=", 1)[0].strip() == key and "=" in raw:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

env_get() {
  local key="$1"
  run_root "$PYTHON_BIN" - "$ENV_FILE" "$key" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
if not path.is_file():
    raise SystemExit(0)
for raw in path.read_text(encoding="utf-8").splitlines():
    if raw.split("=", 1)[0].strip() == key and "=" in raw:
        print(raw.split("=", 1)[1].strip().strip('"').strip("'"))
        break
PY
}

env_has_value() {
  local value
  value="$(env_get "$1")"
  [[ -n "$value" ]]
}

set_env_key() {
  local key="$1"
  local value="$2"
  run_root "$PYTHON_BIN" - "$ENV_FILE" "$key" "$value" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = []
seen = False
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw and raw.split("=", 1)[0].strip() == key:
            lines.append(f"{key}={value}")
            seen = True
        else:
            lines.append(raw)
if not seen:
    lines.append(f"{key}={value}")
path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}

set_env_from_process_if_present() {
  local key="$1"
  local value="${!key:-}"
  if [[ -n "$value" ]]; then
    set_env_key "$key" "$value"
  fi
  return 0
}

sync_env_defaults() {
  local template="$INSTALL_DIR/.env.example"
  [[ -f "$template" && -f "$ENV_FILE" ]] || return 0
  local added=0
  while IFS= read -r line; do
    [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
    local key="${line%%=*}"
    if ! env_key_exists "$key"; then
      printf '\n%s\n' "$line" | run_root tee -a "$ENV_FILE" >/dev/null
      added=$((added + 1))
    fi
  done < "$template"
  [[ "$added" -gt 0 ]] && warn "added $added missing env keys to $ENV_FILE"
  set_env_key "MARINE_TRACK_PROVIDER_PROFILE" "$PROVIDER_PROFILE"
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

prompt_env_value() {
  local key="$1"
  local label="$2"
  local secret="${3:-0}"
  env_has_value "$key" && { success "$key already set"; return 0; }
  [[ "$ASSUME_YES" -eq 1 ]] && return 0
  local value=""
  if [[ "$secret" -eq 1 ]]; then
    read -r -s -p "$label [$key] (Enter to skip): " value
    printf '\n' >&2
  else
    read -r -p "$label [$key] (Enter to skip): " value
  fi
  if [[ -n "$value" ]]; then
    set_env_key "$key" "$value"
  fi
  return 0
}

configure_telegram_access() {
  set_env_from_process_if_present "TELEGRAM_BOT_TOKEN"
  set_env_from_process_if_present "BOT_TOKEN"
  set_env_from_process_if_present "TELEGRAM_ADMIN_IDS"
  if ! env_has_value "TELEGRAM_BOT_TOKEN" && ! env_has_value "BOT_TOKEN" && [[ "$ASSUME_YES" -eq 0 ]]; then
    prompt_env_value "TELEGRAM_BOT_TOKEN" "Telegram bot token from BotFather" 1
  fi
  if ! env_has_value "TELEGRAM_ADMIN_IDS" && [[ "$ASSUME_YES" -eq 0 ]]; then
    prompt_env_value "TELEGRAM_ADMIN_IDS" "Telegram admin ids, comma-separated" 0
  fi
  if ! env_has_value "TELEGRAM_BOT_TOKEN" && ! env_has_value "BOT_TOKEN"; then
    fail "TELEGRAM_BOT_TOKEN is empty. Set it in $ENV_FILE or pass TELEGRAM_BOT_TOKEN before deploy."
  fi
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
}

configure_provider_access() {
  local keys=(
    EARTHDATA_USERNAME EARTHDATA_PASSWORD EARTHDATA_TOKEN
    CDSE_ACCESS_TOKEN CDSE_USERNAME CDSE_PASSWORD CDSE_CLIENT_ID CDSE_CLIENT_SECRET
    SENTINELHUB_ACCESS_TOKEN SENTINELHUB_CLIENT_ID SENTINELHUB_CLIENT_SECRET
    COPERNICUSMARINE_SERVICE_USERNAME COPERNICUSMARINE_SERVICE_PASSWORD
    MARINE_TRACK_AIS_CSV NOAA_MARINECADASTRE_BASE_URL NOAA_MARINECADASTRE_CACHE_DIR
  )
  local key
  for key in "${keys[@]}"; do set_env_from_process_if_present "$key"; done
  [[ "$ASSUME_YES" -eq 1 ]] && { warn "provider key prompts skipped because --yes is set"; return 0; }
  [[ "$PROVIDER_PROFILE" == "core" ]] && { warn "provider profile is core; provider key prompts skipped"; return 0; }

  log "Provider access configuration. Press Enter to skip optional credentials."
  if enable_scene_providers; then
    printf '\nASF / NASA Earthdata: create NASA Earthdata Login; use username/password or EDL token.\n' >&2
    prompt_env_value "EARTHDATA_USERNAME" "Earthdata username" 0
    prompt_env_value "EARTHDATA_PASSWORD" "Earthdata password" 1
    prompt_env_value "EARTHDATA_TOKEN" "Earthdata bearer token" 1

    printf '\nCopernicus Data Space: create CDSE account; use access token or username/password.\n' >&2
    prompt_env_value "CDSE_ACCESS_TOKEN" "CDSE access token" 1
    prompt_env_value "CDSE_USERNAME" "CDSE username" 0
    prompt_env_value "CDSE_PASSWORD" "CDSE password" 1
    prompt_env_value "CDSE_CLIENT_ID" "CDSE OAuth client id" 0
    prompt_env_value "CDSE_CLIENT_SECRET" "CDSE OAuth client secret" 1

    printf '\nSentinel Hub: create OAuth client in Sentinel Hub Dashboard; use client id/secret or token.\n' >&2
    prompt_env_value "SENTINELHUB_ACCESS_TOKEN" "Sentinel Hub access token" 1
    prompt_env_value "SENTINELHUB_CLIENT_ID" "Sentinel Hub OAuth client id" 0
    prompt_env_value "SENTINELHUB_CLIENT_SECRET" "Sentinel Hub OAuth client secret" 1
  fi
  if enable_aux_providers; then
    printf '\nCopernicus Marine: create Copernicus Marine account or login with toolbox.\n' >&2
    prompt_env_value "COPERNICUSMARINE_SERVICE_USERNAME" "Copernicus Marine username" 0
    prompt_env_value "COPERNICUSMARINE_SERVICE_PASSWORD" "Copernicus Marine password" 1

    printf '\nAIS / tracks: local AIS CSV and optional NOAA MarineCadastre mirror/base URL.\n' >&2
    prompt_env_value "MARINE_TRACK_AIS_CSV" "Local AIS CSV path" 0
    prompt_env_value "NOAA_MARINECADASTRE_BASE_URL" "NOAA MarineCadastre daily ZIP base URL" 0
    prompt_env_value "NOAA_MARINECADASTRE_CACHE_DIR" "NOAA AIS cache dir" 0
  fi
  run_root chown root:"$SERVICE_USER" "$ENV_FILE"
  run_root chmod 0640 "$ENV_FILE"
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

project_path() {
  local raw="$1"
  [[ "$raw" = /* ]] && printf '%s' "$raw" || printf '%s/%s' "$INSTALL_DIR" "$raw"
}

prepare_land_mask_once() {
  local auto force mask source cache_dir aoi
  auto="$(env_get MARINE_TRACK_AUTO_UPDATE_LAND_MASK)"; [[ -z "$auto" ]] && auto="1"
  [[ "$auto" =~ ^(1|true|yes|on)$ ]] || { warn "land mask auto-update skipped"; return 0; }
  mask="$(env_get MARINE_TRACK_LAND_MASK_GEOJSON)"
  if [[ -z "$mask" ]]; then
    mask="$INSTALL_DIR/data/masks/land.geojson"
    set_env_key "MARINE_TRACK_LAND_MASK_GEOJSON" "$mask"
  else
    mask="$(project_path "$mask")"
  fi
  force="$(env_get MARINE_TRACK_FORCE_UPDATE_LAND_MASK)"; [[ -z "$force" ]] && force="0"
  if [[ -f "$mask" && "$force" != "1" && "$force" != "true" ]]; then
    success "land mask exists, download skipped: $mask"
    return 0
  fi
  source="$(env_get MARINE_TRACK_LAND_MASK_SOURCE_URL)"; [[ -z "$source" ]] && source="https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
  cache_dir="$(env_get MARINE_TRACK_LAND_MASK_CACHE_DIR)"; [[ -z "$cache_dir" ]] && cache_dir="data/masks/cache"
  cache_dir="$(project_path "$cache_dir")"
  aoi="$(env_get MARINE_TRACK_DEFAULT_AOI)"; [[ -z "$aoi" ]] && aoi="data/aoi/example_black_sea.geojson"
  aoi="$(project_path "$aoi")"
  run_root mkdir -p "$(dirname "$mask")" "$cache_dir"
  run_root chown -R "$SERVICE_USER:$SERVICE_USER" "$(dirname "$mask")" "$cache_dir"
  local args=(update-land-mask --output "$mask" --source "$source" --cache-dir "$cache_dir" --force)
  [[ -f "$aoi" ]] && args+=(--aoi "$aoi")
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/marine-track" "${args[@]}"
}

cleanup_runtime_files() {
  local enabled
  enabled="$(env_get MARINE_TRACK_CLEANUP_ON_DEPLOY)"; [[ -z "$enabled" ]] && enabled="1"
  [[ "$enabled" =~ ^(1|true|yes|on)$ ]] || { warn "cleanup on deploy skipped"; return 0; }
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
import os, sys
path = Path(sys.argv[1])
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
from marine_track.cache_policy import cleanup_runtime
for name, report in cleanup_runtime().items():
    print(f"Cleanup {name}: files={report.removed_files} dirs={report.removed_dirs} bytes={report.removed_bytes}")
PY
}

runtime_check() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" "$INSTALL_DIR/runtime_check.py"
}

telegram_healthcheck() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
import json, os, sys
path = Path(sys.argv[1])
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
if not token:
    raise SystemExit("Telegram healthcheck failed: TELEGRAM_BOT_TOKEN is empty")
try:
    with urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
except HTTPError as exc:
    raise SystemExit(f"Telegram healthcheck failed: HTTP {exc.code}; token is probably invalid") from exc
except URLError as exc:
    raise SystemExit(f"Telegram healthcheck failed: network error: {exc}") from exc
if not payload.get("ok"):
    raise SystemExit(f"Telegram healthcheck failed: {payload}")
user = payload.get("result", {})
print(f"Telegram healthcheck OK: id={user.get('id')} username=@{user.get('username')}")
PY
}

provider_preflight() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" MARINE_TRACK_PROVIDER_PROFILE="$PROVIDER_PROFILE" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
import importlib.util, os, sys
path = Path(sys.argv[1])
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
profile = os.getenv("MARINE_TRACK_PROVIDER_PROFILE", "all").strip().lower()
if profile == "none":
    profile = "core"
checks = [
    ("asf", "scene", ["asf_search"], [["EARTHDATA_USERNAME", "EARTHDATA_TOKEN"]]),
    ("copernicus_cdse", "scene", ["pystac_client"], [["CDSE_ACCESS_TOKEN", "CDSE_USERNAME"]]),
    ("planetary_computer", "scene", ["pystac_client", "planetary_computer"], []),
    ("earthsearch", "scene", ["pystac_client"], []),
    ("sentinelhub", "scene", ["sentinelhub"], [["SENTINELHUB_ACCESS_TOKEN", "SENTINELHUB_CLIENT_ID"]]),
    ("copernicus_marine", "aux", ["copernicusmarine"], [["COPERNICUSMARINE_SERVICE_USERNAME"]]),
    ("local_ais", "aux", ["pandas"], [["MARINE_TRACK_AIS_CSV"]]),
    ("noaa_marinecadastre", "aux", ["pandas"], [["NOAA_MARINECADASTRE_BASE_URL"]]),
]
def enabled(kind: str) -> bool:
    return profile == "all" or (profile == "scene" and kind == "scene") or (profile == "aux" and kind == "aux")
failures = 0
print(f"Provider preflight: profile={profile}")
for name, kind, modules, env_groups in checks:
    if not enabled(kind):
        print(f"- {name}: skipped ({kind})")
        continue
    issues = []
    for module in modules:
        if importlib.util.find_spec(module) is None:
            issues.append(f"missing module {module}")
    for group in env_groups:
        if not any(os.getenv(item, "").strip() for item in group):
            issues.append("optional credentials/env not set: " + " or ".join(group))
    status = "ok" if not issues else "warn"
    if any(item.startswith("missing module") for item in issues):
        status = "fail"; failures += 1
    print(f"- {name}: {status}")
    for issue in issues:
        print(f"  - {issue}")
raise SystemExit(1 if failures else 0)
PY
}

register_commands() {
  run_user "$SERVICE_USER" env HOME="$INSTALL_DIR" "$VENV_DIR/bin/python" - "$ENV_FILE" <<'PY'
from pathlib import Path
import asyncio, os, sys
from telegram import Bot
from marine_track.telegram_commands import BOT_COMMANDS
path = Path(sys.argv[1])
if path.is_file():
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw and not raw.lstrip().startswith("#") and "=" in raw:
            key, value = raw.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
token = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
if not token:
    raise SystemExit("command registration failed: TELEGRAM_BOT_TOKEN is empty")
async def main() -> None:
    await Bot(token).set_my_commands(list(BOT_COMMANDS))
asyncio.run(main())
print("Telegram commands registered")
PY
}

restart_service() {
  [[ "$NO_RESTART" -eq 1 ]] && { warn "restart skipped"; return 0; }
  [[ -f "$UNIT_PATH" ]] || fail "systemd unit missing: $UNIT_PATH"
  run_root systemctl daemon-reload
  run_root systemctl restart "${SERVICE_NAME}.service"
  sleep 2
  systemctl is-active --quiet "${SERVICE_NAME}.service" || { run_root journalctl -u "${SERVICE_NAME}.service" -n 80 --no-pager || true; fail "service did not start"; }
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
telegram_healthcheck=ok
provider_preflight=ok
telegram_commands=registered
EOF
  run_root chown "$SERVICE_USER:$SERVICE_USER" "$STATE_FILE"
}

main() {
  normalize_provider_profile
  print_status
  [[ "$STATUS_ONLY" -eq 1 ]] && exit 0
  require_ready_install
  confirm "Deploy Marine Track bot from $REPO_ROOT to $INSTALL_DIR with provider profile '$PROVIDER_PROFILE'?" || fail "cancelled"
  ensure_root_access
  ensure_systemd_available
  exec 9>"$DEPLOY_LOCK"
  flock -n 9 || fail "another deploy is running: $DEPLOY_LOCK"
  install_system_packages
  precheck_source
  copy_project
  sync_env_defaults
  configure_telegram_access
  configure_provider_access
  ensure_venv_and_deps
  prepare_land_mask_once
  cleanup_runtime_files
  runtime_check
  telegram_healthcheck
  provider_preflight
  register_commands
  restart_service
  write_state
  success "deploy complete: $(git_rev)"
}

main "$@"
