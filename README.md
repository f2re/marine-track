# Marine Track

Marine Track — MVP-система для поиска спутниковых сцен по акватории и первичной детекции судов с отправкой результатов в Telegram.

Текущий фокус проекта: не обучать нейросеть преждевременно, а собрать воспроизводимый pipeline:

```text
AOI или bbox → поиск Sentinel-сцен → выбор срока → GeoTIFF/COG asset → AOI crop → optional land/shoreline mask → local CFAR detector → обзорный PNG → crop судов → GeoJSON/CSV/Parquet/report.json → Telegram
```

## Что уже реализовано

- Telegram bot `marine-track-bot`.
- Slash-команды `/dates`, `/bboxdates`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`.
- Поиск доступных сроков снимков за последние 12 часов по AOI или bbox.
- `scene_registry.json`: token сцены, provider, sensor, assets, AOI geometry.
- Detection-aware поиск сцен: STAC-провайдеры фильтруются по наличию GeoTIFF/COG assets.
- Для Sentinel-1 `/detectbbox` предпочитает Planetary Computer `sentinel-1-rtc`.
- Materializer выбирает full-resolution GeoTIFF/COG asset, подписывает Planetary Computer URL при возможности и вырезает AOI.
- Опциональная land/shoreline mask по GeoJSON полигонам суши в EPSG:4326.
- Local-CFAR style detector для bright compact targets.
- Overview PNG с точками/номерами судов.
- Crop PNG по каждому найденному судну.
- Вывод GeoJSON, CSV, Parquet и `report.json`.
- Install/deploy scripts для systemd-сервиса.

## Что пока не реализовано

- Автоматическое скачивание/обновление coastline/land mask. Сейчас маска подключается файлом GeoJSON через `.env`.
- Полноценный Sentinel-2 band stack B02/B03/B04/B08 + SCL/cloud/water mask.
- Wake association вокруг каждого судна.
- Heading/speed enrichment из wake geometry.
- AIS track rendering на crop.
- Обработка ASF ZIP/GRD через SNAP/pyroSAR. Сейчас такие assets намеренно не обрабатываются как GeoTIFF.

## Быстрый старт для разработки

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
python -m pytest -q
ruff check src tests
```

CLI:

```bash
marine-track --help
marine-track run \
  --aoi data/aoi/example_black_sea.geojson \
  --from 2026-07-01T00:00:00Z \
  --to 2026-07-06T00:00:00Z \
  --sensor auto \
  --output runs/black_sea_20260706
```

## Telegram bot

Основные команды:

```text
/dates [auto|sentinel1|sentinel2] [hours]
/bboxdates [auto|sentinel1|sentinel2] west south east north [hours]
/image token
/detect token
/detectbbox [auto|sentinel1|sentinel2] west south east north [hours]
/status
/whoami
```

Примеры:

```text
/dates sentinel1 12
/bboxdates sentinel1 36.5 43.8 38.5 45.0 12
/detect <token из /dates или /bboxdates>
/detectbbox sentinel1 36.5 43.8 38.5 45.0 12
```

`/detectbbox` — основной быстрый сценарий: найти свежую detection-capable сцену по bbox, сохранить token, вырезать AOI, запустить detector и отправить результаты.

## Установка Telegram bot на сервер

1. Склонировать репозиторий:

```bash
git clone https://github.com/f2re/marine-track.git
cd marine-track
```

2. Создать бота через BotFather и получить Telegram token.

3. Узнать свой Telegram user id. Можно запустить бота без `TELEGRAM_ADMIN_IDS`, выполнить `/whoami`, затем добавить id в `.env`.

4. Установить сервис:

```bash
TELEGRAM_BOT_TOKEN='<bot-token>' TELEGRAM_ADMIN_IDS='<your-telegram-id>' bash install_telegram_bot.sh --yes
```

По умолчанию используется:

```text
/opt/marine_track
/etc/systemd/system/marine-track-bot.service
```

5. Проверить статус:

```bash
bash install_telegram_bot.sh --status
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 100 --no-pager
```

## Настройка `.env`

Шаблон: `.env.example`.

Минимум для Telegram:

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
```

Опционально для подавления береговых ложных целей:

```text
MARINE_TRACK_LAND_MASK_GEOJSON=/opt/marine_track/data/masks/land.geojson
MARINE_TRACK_SHORELINE_BUFFER_M=500
```

`MARINE_TRACK_LAND_MASK_GEOJSON` должен указывать на GeoJSON с полигонами суши в EPSG:4326. Маска перепроецируется в CRS растра, буферизуется на `MARINE_TRACK_SHORELINE_BUFFER_M` метров и применяется до local CFAR.

Для Sentinel/провайдеров при необходимости:

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

`/detectbbox` сначала опирается на STAC/COG источники. Для Planetary Computer assets используется `planetary-computer` signing, если библиотека доступна.

## Обновление после `git pull`

```bash
git pull
bash deploy_telegram_bot.sh --yes
cd /opt/marine_track
source .venv/bin/activate
python register_telegram_commands.py
```

При изменении системных geospatial-зависимостей:

```bash
bash deploy_telegram_bot.sh --install-system-packages --yes
```

## Выходные файлы детекции

```text
MARINE_TRACK_OUTPUT_DIR/detections/<token>/overview.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/crops/*.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.geojson
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.csv
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.parquet
MARINE_TRACK_OUTPUT_DIR/detections/<token>/report.json
```

`report.json` содержит параметры detector-а, land mask settings, raster key, product id, acquisition time, число детекций, paths crop-файлов и provenance.

## Текущий план реализации

См. `docs/IMPLEMENTATION_PLAN.md`.

Ближайший следующий этап: автоматическое получение coastline/land mask, затем wake association и AIS track rendering.
