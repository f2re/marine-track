# Troubleshooting Marine Track Telegram Bot

## Bot does not answer

Check service state and logs:

```bash
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 120 --no-pager
```

Run the local smoke-check:

```bash
cd /opt/marine_track
sudo -u marinetrack .venv/bin/python -m marine_track.smoke_check --base-dir /opt/marine_track --env-file /opt/marine_track/.env
```

If `TELEGRAM_ADMIN_IDS` is set, only those Telegram user ids can run protected commands. `/whoami` shows the current id.

## TELEGRAM_BOT_TOKEN is empty

Deploy stops before restart when the token is empty.

Fix:

```bash
sudoedit /opt/marine_track/.env
sudo chown root:marinetrack /opt/marine_track/.env
sudo chmod 0640 /opt/marine_track/.env
bash deploy_telegram_bot.sh --providers all --yes
```

Set:

```text
TELEGRAM_BOT_TOKEN=<bot-token-from-BotFather>
```

`BOT_TOKEN` is still accepted as a fallback, but `TELEGRAM_BOT_TOKEN` is the primary key.

## Token invalid

Deploy runs Telegram `getMe` before restarting the service. If the token is invalid, deploy fails with `HTTP 401` or a Telegram API error and leaves the old service state untouched.

Create or copy the token again from BotFather, update `/opt/marine_track/.env`, restore permissions and rerun deploy.

## `.env` permission denied

Expected mode:

```text
/opt/marine_track/.env  root:marinetrack 0640
```

Fix:

```bash
sudo chown root:marinetrack /opt/marine_track/.env
sudo chmod 0640 /opt/marine_track/.env
sudo systemctl restart marine-track-bot.service
```

The service runs as `marinetrack` and reads `.env` through group access.

## Service restart loop

Inspect the Python exception:

```bash
sudo journalctl -u marine-track-bot.service -n 200 --no-pager
```

Then run:

```bash
cd /opt/marine_track
sudo -u marinetrack .venv/bin/python runtime_check.py
sudo -u marinetrack .venv/bin/python -m marine_track.smoke_check --base-dir /opt/marine_track --env-file /opt/marine_track/.env --skip-telegram
```

Common causes are missing provider packages for the selected `MARINE_TRACK_PROVIDER_PROFILE`, invalid numeric env values, missing default AOI or unwritable output/cache dirs.

## Land mask download failed

Land mask is optional. Deploy warns and continues without land/shoreline suppression if automatic download fails.

To retry manually:

```bash
cd /opt/marine_track
sudo -u marinetrack .venv/bin/marine-track update-land-mask \
  --output data/masks/land.geojson \
  --cache-dir data/masks/cache \
  --aoi data/aoi/example_black_sea.geojson \
  --force
```

Then set `MARINE_TRACK_LAND_MASK_GEOJSON=data/masks/land.geojson` in `.env` and redeploy.

## Provider modules missing

`runtime_check.py` validates imports by provider profile:

```text
all   = core + scene + aux
scene = core + scene
aux   = core + aux
core  = core only
```

Fix by redeploying with the intended profile:

```bash
bash deploy_telegram_bot.sh --providers all --yes
```

Missing credentials are warnings in provider preflight. Missing Python modules for the active profile are failures.

## No GeoTIFF/COG scene found

Some providers return metadata, preview images or ASF ZIP/GRD products that the current detector cannot process as full-resolution GeoTIFF/COG.

Use:

```text
/bboxdates sentinel1 36.5 43.8 38.5 45.0 12
```

Then choose a scene with `🔎 Детекция`. For Sentinel-1 detection, Planetary Computer Sentinel-1 RTC COG scenes are useful when the required account/API/SAS access is available; otherwise use the CDSE COG/OData fallback after the provider migration.
