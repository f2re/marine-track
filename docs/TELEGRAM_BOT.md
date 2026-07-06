# Telegram bot deployment

Marine Track can run as a Telegram bot on top of the existing CLI pipeline. The bot is intentionally small: it searches Sentinel scenes by configured AOI or by bbox and writes provenance files for later processing.

## Commands

```text
/start   — start message
/help    — command examples
/status  — effective configuration
/whoami  — Telegram user id for TELEGRAM_ADMIN_IDS
/search [auto|sentinel1|sentinel2] [hours]
/bbox [auto|sentinel1|sentinel2] west south east north [hours]
```

Examples:

```text
/search sentinel1 72
/bbox sentinel1 36.5 43.8 38.5 45.0 72
```

## Environment

Main variables:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_IDS=
MARINE_TRACK_DEFAULT_AOI=data/aoi/example_black_sea.geojson
MARINE_TRACK_OUTPUT_DIR=runs/telegram
MARINE_TRACK_DEFAULT_SENSOR=auto
MARINE_TRACK_DEFAULT_LOOKBACK_HOURS=72
MARINE_TRACK_MAX_RESULTS=10
MARINE_TRACK_MAX_CONCURRENT_JOBS=1
```

If `TELEGRAM_ADMIN_IDS` is empty, `/search` and `/bbox` are open to all users. If it is set, only those numeric Telegram ids can run operational commands. Use `/whoami` to get the id.

## Install

From repository root:

```bash
TELEGRAM_BOT_TOKEN='<bot-token>' TELEGRAM_ADMIN_IDS='<your-id>' bash install_telegram_bot.sh --yes
```

Default paths:

```text
/opt/marine_track
/etc/systemd/system/marine-track-bot.service
```

Status:

```bash
bash install_telegram_bot.sh --status
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 100 --no-pager
```

## Deploy after git pull

```bash
git pull
bash deploy_telegram_bot.sh --yes
```

With system package refresh:

```bash
bash deploy_telegram_bot.sh --install-system-packages --yes
```

Deploy keeps installed `.env` and `runs/` intact, syncs code to `/opt/marine_track`, updates the virtual environment, runs `runtime_check.py`, restarts the service and tries to register slash commands.

## Command registration

Manual registration from installed directory:

```bash
cd /opt/marine_track
source .venv/bin/activate
python register_telegram_commands.py
```

## Runtime check

```bash
python runtime_check.py
```

The check verifies imports, default AOI existence, output directory writability and numeric environment variables. It does not perform network calls to Sentinel providers.
