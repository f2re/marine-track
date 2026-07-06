# Telegram bot deployment

Marine Track can run as a Telegram bot on top of the existing CLI pipeline. The bot searches Sentinel scenes by configured AOI or by bbox, writes provenance files, sends preview/quicklook for selected acquisition times, and can run the first detection skeleton for scene tokens that contain a processable GeoTIFF/COG asset.

## Commands

```text
/start   — start message
/help    — command examples
/status  — effective configuration
/whoami  — Telegram user id for TELEGRAM_ADMIN_IDS
/dates [auto|sentinel1|sentinel2] [hours]
/bboxdates [auto|sentinel1|sentinel2] west south east north [hours]
/image token
/detect token
/detectbbox [auto|sentinel1|sentinel2] west south east north [hours]
```

Examples:

```text
/dates sentinel1 12
/bboxdates sentinel1 36.5 43.8 38.5 45.0 12
/image 1a2b3c4d5e6f
/detect 1a2b3c4d5e6f
/detectbbox sentinel1 36.5 43.8 38.5 45.0 12
```

`/dates` and `/bboxdates` search available scenes for the last 12 hours by default. The bot sends an inline keyboard with acquisition times. Each row has two actions:

- `📷` downloads and sends the best available preview asset.
- `🔎 Детекция` runs detection for the same scene token.

Preview priority: thumbnail, rendered preview, overview, preview, quicklook, browse, visual/true-color assets, then image-like assets.

`/detect` supports only full-resolution GeoTIFF/COG assets. It intentionally does not process ASF ZIP/GRD archives as rasters. If a selected scene has only preview or archive assets, the bot returns a clear error.

`/detectbbox` searches only detection-capable STAC providers and filters scenes to those that expose GeoTIFF/COG assets. For Sentinel-1 this prefers Planetary Computer `sentinel-1-rtc` before falling back to other STAC sources. The AOI geometry is persisted in `scene_registry.json`, so the raster materializer crops the source raster to the requested aquatory before running the detector.

Detection output:

```text
MARINE_TRACK_OUTPUT_DIR/detections/<token>/overview.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/crops/*.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.geojson
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.csv
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.parquet
MARINE_TRACK_OUTPUT_DIR/detections/<token>/report.json
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

If `TELEGRAM_ADMIN_IDS` is empty, operational commands are open to all users. If it is set, only those numeric Telegram ids can run them. Use `/whoami` to get the id.

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

## Scene registry

The bot writes scene selections into:

```text
MARINE_TRACK_OUTPUT_DIR/scene_registry.json
MARINE_TRACK_OUTPUT_DIR/previews/
```

The registry maps short tokens to full scene metadata, provider, sensor, AOI geometry, `scenes.json` and `assets.csv`. Detection commands load the same token from this registry.

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
