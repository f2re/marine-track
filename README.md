# Marine Track

Marine Track — MVP-система для поиска спутниковых сцен по акватории и первичной детекции судов с отправкой результатов в Telegram.

Текущий pipeline:

```text
AOI или bbox → кешированный поиск Sentinel-сцен → выбор срока → кешированный GeoTIFF/COG asset → AOI crop → land/shoreline mask → local CFAR detector → обзорный PNG → crop судов → GeoJSON/CSV/Parquet/report.json → Telegram
```

## Основное правило установки

В проекте поддерживаются только два эксплуатационных shell-скрипта:

```bash
bash install_telegram_bot.sh --providers all
bash deploy_telegram_bot.sh --providers all
```

Все прежние wrapper/fix/helper scripts выведены из эксплуатации. Их логика встроена в `deploy_telegram_bot.sh`: запрос Telegram/provider-доступов, установка provider extras, Telegram `getMe` healthcheck, provider preflight, одноразовая подготовка land mask, cleanup, регистрация Telegram-команд и рестарт systemd.

## Что уже реализовано

- Telegram bot `marine-track-bot`.
- Главное inline-меню: `Найти суда`, `Сроки снимков`, `Повторить район`, `Сроки района`, `Статус`, `Помощь`, `Мой ID`.
- Быстрый сценарий без ручного token: default AOI → свежая detection-capable сцена → детекция → файлы.
- Последний bbox пользователя: `/bboxdates` и `/detectbbox` сохраняют район для повторного запуска кнопками.
- Slash-команды `/start`, `/menu`, `/help`, `/dates`, `/bboxdates`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`.
- `scene_registry.json`: token сцены, provider, sensor, assets, AOI geometry.
- Реальные scene providers: ASF, Copernicus CDSE STAC, Planetary Computer STAC, Sentinel Hub Catalog, EarthSearch STAC.
- Auxiliary providers: Copernicus Marine toolbox, local AIS CSV, NOAA MarineCadastre daily archives.
- Provider profiles: `all`, `scene`, `aux`, `core`, `none`.
- TTL-кеш scene-search, чтобы минимизировать STAC/provider API calls.
- Общий raster cache: один и тот же product/asset/AOI не скачивается повторно.
- Автоматическая сборка land/shoreline mask из URL или локального ZIP/SHP/GeoJSON.
- Local-CFAR style detector для bright compact targets.
- Консервативная wake-axis association вокруг каждого судна через Canny+Hough; heading сохраняется с флагом неоднозначности 180°.
- Overview PNG с точками/номерами судов.
- Crop PNG по каждому найденному судну, включая wake-axis overlay при наличии.
- Вывод GeoJSON, CSV, Parquet и `report.json`.

## Что пока не реализовано

- Полноценный Sentinel-2 band stack B02/B03/B04/B08 + SCL/cloud/water mask.
- Speed enrichment из wake geometry.
- AIS track rendering на crop.
- Обработка ASF ZIP/GRD через SNAP/pyroSAR.

## Установка на сервер

```bash
git clone https://github.com/f2re/marine-track.git
cd marine-track
TELEGRAM_BOT_TOKEN='<bot-token>' TELEGRAM_ADMIN_IDS='<your-telegram-id>' bash install_telegram_bot.sh --providers all --yes
```

Интерактивно, с запросом Telegram token и provider-доступов:

```bash
bash install_telegram_bot.sh --providers all
```

Профили provider-зависимостей:

```text
all    = core + scene providers + auxiliary providers
scene  = core + ASF/STAC/Planetary Computer/Sentinel Hub
aux    = core + Copernicus Marine
core   = только core; provider-пакеты не ставятся
none   = alias для core
```

Проверка статуса:

```bash
bash install_telegram_bot.sh --status
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 100 --no-pager
```

## Деплой после `git pull`

```bash
git pull
bash deploy_telegram_bot.sh --providers all --yes
```

Интерактивный деплой с запросом новых/пустых доступов:

```bash
git pull
bash deploy_telegram_bot.sh --providers all
```

При изменении системных geospatial-зависимостей:

```bash
bash deploy_telegram_bot.sh --install-system-packages --providers all --yes
```

Чтобы пропустить provider-пакеты:

```bash
bash deploy_telegram_bot.sh --providers core --yes
```

## Что делает `deploy_telegram_bot.sh`

1. Копирует текущий checkout в `/opt/marine_track`, не перетирая `.env`, `.venv` и `runs`.
2. Синхронизирует новые ключи из `.env.example` в `/opt/marine_track/.env`.
3. Запрашивает или принимает через environment `TELEGRAM_BOT_TOKEN` и `TELEGRAM_ADMIN_IDS`.
4. Запрашивает provider-доступы для активного профиля.
5. Ставит пакет с нужными extras: `.[providers]`, `.[scene-providers]`, `.[aux-providers]` или core.
6. Один раз собирает land mask, если `MARINE_TRACK_AUTO_UPDATE_LAND_MASK=1`, mask-файл отсутствует и `MARINE_TRACK_FORCE_UPDATE_LAND_MASK=0`.
7. Выполняет cleanup старых кешей/output-файлов по retention.
8. Запускает `runtime_check.py`.
9. Проверяет Telegram token через `getMe`.
10. Выполняет provider preflight без сетевых запросов.
11. Регистрирует Telegram-команды.
12. Перезапускает `marine-track-bot.service`.

Если `TELEGRAM_BOT_TOKEN` пустой или неверный, deploy падает до рестарта сервиса.

## `.env`

Ожидаемые права:

```text
/opt/marine_track/.env  root:marinetrack 0640
```

Минимум:

```text
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_IDS=
MARINE_TRACK_DEFAULT_AOI=data/aoi/example_black_sea.geojson
MARINE_TRACK_OUTPUT_DIR=runs/telegram
MARINE_TRACK_DEFAULT_SENSOR=auto
MARINE_TRACK_DEFAULT_LOOKBACK_HOURS=72
MARINE_TRACK_MAX_RESULTS=10
MARINE_TRACK_MAX_CONCURRENT_JOBS=1
MARINE_TRACK_PROVIDER_PROFILE=all
MARINE_TRACK_DETECTION_MAX_CROPS=10
```

## Cache policy

```text
MARINE_TRACK_CACHE_DIR=runs/cache
MARINE_TRACK_SCENE_SEARCH_TTL_MIN=30
MARINE_TRACK_SCENE_SEARCH_CACHE_RETENTION_DAYS=7
MARINE_TRACK_RASTER_CACHE_RETENTION_DAYS=14
MARINE_TRACK_MASK_CACHE_RETENTION_DAYS=90
MARINE_TRACK_DETECTION_OUTPUT_RETENTION_DAYS=7
MARINE_TRACK_RUN_OUTPUT_RETENTION_DAYS=7
MARINE_TRACK_CLEANUP_ON_DEPLOY=1
```

`scene_search` cache хранит результат поиска scenes по AOI/sensor/lookback/max_results. Пока TTL не истек, `/dates`, `/bboxdates` и `/detectbbox` не делают новый provider API call. После TTL выполняется refresh и появляется шанс поймать новый снимок.

`raster` cache хранит скачанный или AOI-cropped GeoTIFF по ключу provider/product/asset/AOI. Повторная детекция того же снимка и района использует локальный файл.

Старые search-cache, raster-cache, mask-cache и detection outputs удаляются по retention во время install/deploy или вручную через CLI.

Ручная очистка:

```bash
cd /opt/marine_track
source .venv/bin/activate
marine-track cleanup-cache
```

## Land/shoreline mask

При `install_telegram_bot.sh` и `deploy_telegram_bot.sh` маска собирается один раз: если `MARINE_TRACK_LAND_MASK_GEOJSON` уже существует и `MARINE_TRACK_FORCE_UPDATE_LAND_MASK=0`, повторного download не будет.

Настройки:

```text
MARINE_TRACK_LAND_MASK_GEOJSON=/opt/marine_track/data/masks/land.geojson
MARINE_TRACK_SHORELINE_BUFFER_M=500
MARINE_TRACK_AUTO_UPDATE_LAND_MASK=1
MARINE_TRACK_FORCE_UPDATE_LAND_MASK=0
MARINE_TRACK_LAND_MASK_SOURCE_URL=https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip
MARINE_TRACK_LAND_MASK_CACHE_DIR=data/masks/cache
```

Ручная сборка:

```bash
cd /opt/marine_track
source .venv/bin/activate
marine-track update-land-mask \
  --output data/masks/land.geojson \
  --cache-dir data/masks/cache \
  --aoi data/aoi/example_black_sea.geojson \
  --force
```

## Telegram bot

Основной пользовательский сценарий:

```text
/start → 🔎 Найти суда → обзор/crops/files
```

Ручной район сохраняется автоматически:

```text
/detectbbox sentinel1 36.5 43.8 38.5 45.0 12
```

После этого в меню появятся:

```text
↻ Повторить район
🕒 Сроки района
```

Кнопки меню:

```text
🔎 Найти суда       свежая detection-capable сцена по default AOI и детекция
🕒 Сроки снимков    список сцен; дальше 📷 preview или 🔎 детекция
↻ Повторить район   повторная детекция по последнему bbox
🕒 Сроки района      список сцен по последнему bbox
⚙️ Статус           AOI, sensor, lookback, land mask, output dir, last bbox
❓ Помощь            краткая инструкция и примеры
🆔 Мой ID            Telegram id для TELEGRAM_ADMIN_IDS
```

Команды:

```text
/start
/menu
/help
/dates [auto|sentinel1|sentinel2] [hours]
/bboxdates [auto|sentinel1|sentinel2] west south east north [hours]
/image token
/detect token
/detectbbox [auto|sentinel1|sentinel2] west south east north [hours]
/status
/whoami
```

`/detectbbox` показывает `search_cache: hit/refresh`, а итоговая детекция показывает `raster_cache: hit/created`.

## Выходные файлы детекции

```text
MARINE_TRACK_OUTPUT_DIR/detections/<token>/overview.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/crops/*.png
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.geojson
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.csv
MARINE_TRACK_OUTPUT_DIR/detections/<token>/detections.parquet
MARINE_TRACK_OUTPUT_DIR/detections/<token>/report.json
```

## Текущий план реализации

См. `docs/IMPLEMENTATION_PLAN.md` и `docs/UX_REVIEW.md`.

Ближайший следующий этап: AIS track rendering и несколько сохраненных пользовательских AOI/bbox.
