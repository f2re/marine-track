# Marine Track

Marine Track — MVP-система для поиска спутниковых сцен по акватории и первичной детекции судов с отправкой результатов в Telegram.

Текущий pipeline:

```text
AOI или bbox → кешированный поиск Sentinel-сцен → выбор срока → кешированный GeoTIFF/COG asset → AOI crop → land/shoreline mask → local CFAR detector → wake/AIS enrichment → обзорный PNG → crop судов → GeoJSON/CSV/Parquet/report.json → Telegram
```

## Основное правило установки

В проекте поддерживаются только два эксплуатационных shell-скрипта:

```bash
bash install_telegram_bot.sh --providers all
bash deploy_telegram_bot.sh --providers all
```

Все прежние wrapper/fix/helper scripts удалены из рабочего пути. Их логика встроена в `deploy_telegram_bot.sh`: установка provider extras, Telegram `getMe` healthcheck, provider preflight, одноразовая подготовка land mask, cleanup, регистрация Telegram-команд и рестарт systemd.

## Release gate

Перед расширением алгоритмов и новых источников проект должен пройти `docs/RELEASE_GATE.md`: bash syntax, pytest, ruff, clean install, deploy, systemd, Telegram `/start`, `/dates`, `/detectbbox`, land-mask/cache checks.

Пока release gate v0.1 не закрыт на сервере, не добавлять новые providers, Sentinel-2 full stack и ASF ZIP/GRD processing.

## Что уже реализовано

- Telegram bot `marine-track-bot`.
- Главное inline-меню: `Найти суда`, `Сроки снимков`, `Повторить район`, `Сроки района`, `Мои районы`, `Выдача`, `Статус`, `Помощь`, `Мой ID`.
- Быстрый сценарий без ручного token: default AOI → свежая detection-capable сцена → детекция → файлы.
- Сохраненные bbox пользователя: `/bboxdates` и `/detectbbox` сохраняют до 10 районов для повторного запуска кнопками.
- Slash-команды `/start`, `/menu`, `/help`, `/dates`, `/bboxdates`, `/areas`, `/output`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`.
- `scene_registry.json`: token сцены, provider, sensor, assets, AOI geometry.
- Пагинация списка сцен: кнопки `◀️ Назад` и `▶️ Далее` перелистывают локально сохраненный результат без нового provider API search.
- Progress states в Telegram для долгой детекции: search → materialize → detect → render → send.
- Режим выдачи результата per-user: только картинки, только файлы или всё.
- Реальные scene providers: ASF, Copernicus CDSE STAC, Planetary Computer STAC, Sentinel Hub Catalog, EarthSearch STAC.
- Auxiliary providers: Copernicus Marine toolbox, local AIS CSV, NOAA MarineCadastre daily archives.
- Provider profiles: `all`, `scene`, `aux`, `core`.
- TTL-кеш scene-search, чтобы минимизировать STAC/provider API calls.
- Общий raster cache: один и тот же product/asset/AOI не скачивается повторно.
- Автоматическая сборка land/shoreline mask из URL или локального ZIP/SHP/GeoJSON.
- Local-CFAR detector с physical scale, local contrast, shape metrics и confidence provenance.
- Консервативная wake-axis association вокруг каждого судна через Canny+Hough; heading сохраняется с флагом неоднозначности 180°.
- Experimental wake speed enrichment: wavelength по cross-axis profile peaks, скорость по deep-water Kelvin approximation, результат помечен experimental.
- AIS enrichment: ближайший интерполированный AIS track point, MMSI/distance/SOG/COG в validation/metadata, AIS track overlay на overview/crop.
- Overview PNG с точками/номерами судов, wake axis и AIS track при наличии.
- Crop PNG по каждому найденному судну, включая wake-axis и AIS-track overlay при наличии.
- Вывод GeoJSON, CSV, Parquet и `report.json`.

## Что пока не реализовано

- Lock-файлы для конкурентного скачивания одного raster asset.
- Полноценный Sentinel-2 band stack B02/B03/B04/B08 + SCL/cloud/water mask.
- Обработка ASF ZIP/GRD через SNAP/pyroSAR.

## Установка на сервер

```bash
git clone https://github.com/f2re/marine-track.git
cd marine-track
TELEGRAM_BOT_TOKEN='<bot-token>' TELEGRAM_ADMIN_IDS='<your-telegram-id>' bash install_telegram_bot.sh --providers all --yes
```

Интерактивно, с запросом Telegram token:

```bash
bash install_telegram_bot.sh --providers all
```

Provider-доступы задаются через `/opt/marine_track/.env` или environment; deploy проверяет их через provider preflight без сетевых запросов.

Профили provider-зависимостей:

```text
all    = core + scene providers + auxiliary providers
scene  = core + ASF/STAC/Planetary Computer/Sentinel Hub
aux    = core + Copernicus Marine
core   = только core; provider-пакеты не ставятся
```

Проверка статуса:

```bash
bash install_telegram_bot.sh --status
sudo systemctl status marine-track-bot.service --no-pager
sudo journalctl -u marine-track-bot.service -n 100 --no-pager
```

Локальный smoke-check без запуска polling:

```bash
cd /opt/marine_track
sudo -u marinetrack .venv/bin/python -m marine_track.smoke_check --base-dir /opt/marine_track --env-file /opt/marine_track/.env
```

## Деплой после `git pull`

```bash
git pull
bash deploy_telegram_bot.sh --providers all --yes
```

Интерактивный деплой с запросом Telegram token, если он пустой:

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

## AIS enrichment

AIS enrich работает, если задан локальный CSV:

```text
MARINE_TRACK_AIS_CSV=/path/to/ais.csv
MARINE_TRACK_AIS_MATCH_WINDOW_MIN=30
MARINE_TRACK_AIS_TRACK_WINDOW_MIN=60
MARINE_TRACK_AIS_MAX_DISTANCE_M=3000
```

Формат CSV:

```text
mmsi,time,lon,lat,sog_knots,cog_deg
```

При совпадении detection ↔ AIS бот пишет `validation_status=ais_matched`, добавляет `validation.ais`, сохраняет AIS track в `metadata.ais.track`, рисует AIS track на overview/crop и использует AIS SOG/COG как внешний reference speed/heading, если собственная оценка не задана.

## Telegram workflow

Основной сценарий:

```text
/start → 🔎 Найти суда → progress states → результат
```

Перед детекцией можно выбрать режим выдачи:

```text
/output
📤 Выдача
```

Доступные режимы:

```text
🖼 Картинки  overview.png и crop судов
📄 Файлы     GeoJSON, CSV, Parquet, report.json
🧾 Всё       картинки и файлы
```

## Что делает `deploy_telegram_bot.sh`

1. Копирует текущий checkout в `/opt/marine_track`, не перетирая `.env`, `.venv`, `runs` и сгенерированный land mask.
2. Синхронизирует новые ключи из `.env.example` в `/opt/marine_track/.env`.
3. Запрашивает или принимает через environment `TELEGRAM_BOT_TOKEN` и `TELEGRAM_ADMIN_IDS`.
4. Ставит пакет с нужными extras: `.[providers]`, `.[scene-providers]`, `.[aux-providers]` или core.
5. Один раз собирает land mask, если `MARINE_TRACK_AUTO_UPDATE_LAND_MASK=1`, mask-файл отсутствует и `MARINE_TRACK_FORCE_UPDATE_LAND_MASK=0`.
6. Выполняет cleanup старых кешей/output-файлов по retention.
7. Запускает `runtime_check.py`.
8. Выполняет provider preflight без сетевых запросов.
9. Проверяет Telegram token через `getMe`.
10. Регистрирует Telegram-команды.
11. Перезапускает `marine-track-bot.service`.

Если `TELEGRAM_BOT_TOKEN` пустой или неверный, deploy падает до рестарта сервиса.

Recovery для пустого или неверного token:

```bash
sudoedit /opt/marine_track/.env
sudo chown root:marinetrack /opt/marine_track/.env
sudo chmod 0640 /opt/marine_track/.env
bash deploy_telegram_bot.sh --providers all --yes
```
