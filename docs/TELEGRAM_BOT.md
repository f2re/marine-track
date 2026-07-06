# Telegram bot deployment

Marine Track can run as a Telegram bot on top of the detection pipeline. The bot searches Sentinel scenes by configured AOI or bbox, writes provenance files, sends preview/quicklook for selected acquisition times, and can run detection for scene tokens that contain a processable GeoTIFF/COG asset.

## Commands

```text
/start
/help
/status
/whoami
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

`/detect` supports only full-resolution GeoTIFF/COG assets. It intentionally does not process ASF ZIP/GRD archives as rasters. If a selected scene has only preview or archive assets, the bot returns a clear error.

`/detectbbox` searches only detection-capable STAC providers and filters scenes to those that expose GeoTIFF/COG assets. For Sentinel-1 this prefers Planetary Computer `sentinel-1-rtc`. The AOI geometry is persisted in `scene_registry.json`; the materializer reprojects it to the raster CRS and crops the source raster before running detection.

## Land and shoreline suppression

Detection can optionally suppress land and a shoreline buffer before local CFAR. Set:

```text
MARINE_TRACK_LAND_MASK_GEOJSON=/opt/marine_track/data/masks/land.geojson
MARINE_TRACK_SHORELINE_BUFFER_M=500
```

The GeoJSON must contain land polygons in EPSG:4326 lon/lat coordinates. At runtime the mask is reprojected to the raster CRS, buffered, rasterized and applied as NaN pixels before normalization and detection. If `MARINE_TRACK_LAND_MASK_GEOJSON` is empty, no land mask is applied.

## Detection output

```text
MARINE_TRACK_OUTPUT_DIR/detections/<token>/overview.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/crops/*.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.geojson
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.csv
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.parquet
MARINE_TRACK_OUTPUT_DIR/detections/<token>/report.json
```

`report.json` contains product provenance, raster key/path, AOI crop status, land mask settings, detector parameters and detections.

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
MARINE_TRACK_DETECTION_MAX_CROPS=10
MARINE_TRACK_LAND_MASK_GEOJSON=
MARINE_TRACK_SHORELINE_BUFFER_M=500
```

Provider variables, when needed:

```text
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
EARTHDATA_TOKEN=
CDSE_CLIENT_ID=
CDSE_CLIENT_SECRET=
CDSE_USERNAME=
CDSE_PASSWORD=
SENTINELHUB_CLIENT_ID=
SENTINELHUB_CLIENT_SECRET=
COPERNICUSMARINE_SERVICE_USERNAME=
COPERNICUSMARINE_SERVICE_PASSWORD=
GFW_API_TOKEN=
AISHUB_API_KEY=
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

Status and logs:

```bash
bash install_telegram_bot.sh --status
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 100 --no-pager
```

## Deploy after git pull

```bash
git pull
python -m pytest -q
ruff check src tests
bash deploy_telegram_bot.sh --yes
cd /opt/marine_track
source .venv/bin/activate
python register_telegram_commands.py
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

## Runtime check

```bash
python runtime_check.py
```

The check verifies imports, default AOI existence, optional land mask path, output directory writability and numeric environment variables. It does not perform network calls to Sentinel providers.
