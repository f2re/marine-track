# Провайдеры доступа Marine Track

Документ фиксирует только реально реализованные провайдеры. Источники без рабочего кода не должны попадать в `config/sources.yaml` priority.

## Единый способ установки и деплоя

Поддерживаются только два эксплуатационных shell-скрипта:

```bash
bash install_telegram_bot.sh --providers all
bash deploy_telegram_bot.sh --providers all
```

`deploy_telegram_bot.sh` содержит всю логику, которая раньше была вынесена в отдельные helper scripts: запрос ключей, provider preflight, Telegram healthcheck, регистрация команд, подготовка land mask и cleanup. Отдельных provider configure/preflight entrypoints в рабочем пути нет.

## Provider dependency profiles

Provider-пакеты вынесены в optional extras. Это позволяет поставить все источники или сознательно пропустить тяжелые/неиспользуемые провайдеры.

```bash
# Все провайдеры: scene + auxiliary. Интерактивно спросит ключи активных providers.
bash install_telegram_bot.sh --providers all
bash deploy_telegram_bot.sh --providers all

# Неинтерактивно: доступы должны быть в environment или .env.
bash install_telegram_bot.sh --providers all --yes
bash deploy_telegram_bot.sh --providers all --yes

# Только спутниковые scene providers: ASF/STAC/Planetary Computer/Sentinel Hub
bash install_telegram_bot.sh --providers scene

# Только auxiliary providers: Copernicus Marine плюс core AIS adapters
bash install_telegram_bot.sh --providers aux

# Только core, без provider-пакетов
bash install_telegram_bot.sh --providers core --yes
```

Профиль записывается в `.env` как `MARINE_TRACK_PROVIDER_PROFILE`. `runtime_check.py` читает `.env` и проверяет только выбранный набор provider modules. Если профиль `core`, scene/aux provider packages не требуются и runtime-check их не валит.

Соответствие extras:

| Profile | pip target | Проверяются runtime-check |
|---|---|---|
| `all` | `.[providers]` | core + scene + aux |
| `scene` | `.[scene-providers]` | core + scene |
| `aux` | `.[aux-providers]` | core + aux |
| `core` | `.` | only core |

## Интерактивная настройка ключей

`install_telegram_bot.sh` при первичной установке делегирует настройку в `deploy_telegram_bot.sh`. В интерактивном режиме deploy проходит по активным провайдерам выбранного профиля, показывает краткую инструкцию и предлагает заполнить недостающие значения в `.env`. Уже заполненные значения не перезаписываются.

Проверка provider configuration без сетевых запросов встроена в deploy. Она падает только при отсутствии установленных provider-модулей, выбранных профилем. Это import/config check, а не readiness: DNS, auth, quota, подписывание и чтение raster она не подтверждает. Перед operational release нужен отдельный live catalog + sign + range-read canary без записи secrets в лог.

## Scene providers

| Provider | Sensor | Код | Доступ | Примечание |
|---|---|---|---|---|
| `asf` | Sentinel-1 | `marine_track.data_sources.asf_provider.ASFProvider` | Search без ключа, download через NASA Earthdata | Search/preview/archive; ZIP/GRD не обрабатывается как GeoTIFF в текущем detection MVP. |
| `copernicus_cdse` | Sentinel-1/2 | `marine_track.data_sources.stac_provider.STACProvider` | CDSE STAC + asset-specific auth/alternates | Целевой endpoint `https://stac.dataspace.copernicus.eu/v1/`; текущий код требует migration и typed asset/auth/sidecar contract. |
| `planetary_computer` | Sentinel-1 RTC/GRD, Sentinel-2 L2A | `STACProvider` | STAC discovery; asset signing/auth flow | SDK может работать без subscription key с более строгими лимитами, но конкретный S1 asset требует live sign/range-read preflight. |
| `earthsearch` | Sentinel-2 L2A | `STACProvider` | Public HTTPS STAC/assets для текущей S2 конфигурации | Upstream имеет S1 GRD, но его `s3://` requester-pays materialization не поддержан и может требовать AWS credentials/cost. |
| `sentinelhub` | Sentinel-1/2 | `marine_track.data_sources.sentinelhub_provider.SentinelHubProvider` | OAuth client credentials или access token | Catalog provider; не гарантирует direct processable COG и не считается бесплатным без проверки quota/contract. |

## Auxiliary providers

| Provider | Код | Доступ | Назначение |
|---|---|---|---|
| `copernicus_marine` | `marine_track.copernicus_marine_provider.CopernicusMarineProvider` | Official `copernicusmarine` toolbox; optional username/password | Ветер, волны, течения, SST для валидации/контекста. |
| `local_ais` | `marine_track.ais_sources.LocalAISProvider` | Локальный CSV | Валидация координат/курса/скорости по локальному AIS/track dataset. |
| `noaa_marinecadastre` | `marine_track.noaa_ais_source.NOAAMarineCadastreProvider` | Public daily ZIP archive; base URL задается явно | Исторические AIS CSV ZIP-файлы, в основном US waters. |

## Переменные окружения

### Provider profile

```text
MARINE_TRACK_PROVIDER_PROFILE=all
```

Допустимые значения: `all`, `scene`, `aux`, `core`. Значение управляет установкой и проверкой Python provider packages. Настройки доступа ниже всё равно можно хранить в `.env`; они будут использованы, когда соответствующий provider установлен.

### ASF / NASA Earthdata

```text
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
EARTHDATA_TOKEN=
```

Как получить: зарегистрировать NASA Earthdata Login account, затем использовать username/password или создать bearer token в профиле Earthdata. ASF search работает без credentials. Для скачивания продуктов нужен Earthdata Login. Текущий detection pipeline не обрабатывает ASF ZIP/GRD как GeoTIFF.

### Copernicus Data Space Ecosystem

```text
CDSE_ACCESS_TOKEN=
CDSE_STAC_URL=https://stac.dataspace.copernicus.eu/v1/
CDSE_STAC_SENTINEL1_COLLECTION=sentinel-1-grd
CDSE_STAC_SENTINEL2_COLLECTION=sentinel-2-l2a
CDSE_ODATA_URL=https://catalogue.dataspace.copernicus.eu/odata/v1/Products
CDSE_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
CDSE_USERNAME=
CDSE_PASSWORD=
```

Как получить: создать аккаунт Copernicus Data Space Ecosystem. Если `CDSE_ACCESS_TOKEN` задан, он используется как bearer token. Если заданы `CDSE_USERNAME` и `CDSE_PASSWORD`, код получает token через OAuth password grant. По умолчанию используется public client `cdse-public`; при необходимости можно задать собственный client id/secret. `CDSE_STAC_*` и `CDSE_ODATA_URL` — целевой provider contract; миграция к ним отмечена в `docs/IMPLEMENTATION_PLAN.md`.

### Planetary Computer

STAC discovery может быть публичным. Dataset page описывает account/API/SAS flow, а официальный SDK допускает anonymous use с более строгими rate limits. Для materialization обязателен live sign + range-read preflight конкретного asset; token/SAS query не сохраняется в report. Для этого нужен профиль `all` или `scene`.

### EarthSearch

Для текущего Sentinel-2 HTTPS path дополнительные credentials обычно не требуются; используется public best-effort STAC Element84 Earth Search v1. Upstream Sentinel-1 `s3://` requester-pays path в текущем materializer не поддержан и не считается credentials-free. Для provider нужен профиль `all` или `scene`.

### Sentinel Hub

```text
SENTINELHUB_ACCESS_TOKEN=
SENTINELHUB_CLIENT_ID=
SENTINELHUB_CLIENT_SECRET=
SENTINELHUB_TOKEN_URL=https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token
SENTINELHUB_CATALOG_URL=https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search
```

Как получить: в Sentinel Hub Dashboard создать OAuth client и взять client id/client secret, либо использовать access token. Для Copernicus Data Space Sentinel Hub services переопределите `SENTINELHUB_TOKEN_URL` и `SENTINELHUB_CATALOG_URL` на CDSE endpoints. Для этого нужен профиль `all` или `scene`.

### Copernicus Marine

```text
COPERNICUSMARINE_SERVICE_USERNAME=
COPERNICUSMARINE_SERVICE_PASSWORD=
```

Как получить: создать Copernicus Marine account. Если пользователь уже выполнил login через toolbox, username/password можно не задавать. Для server deployment лучше задать обе переменные в `.env`. Для этого нужен профиль `all` или `aux`.

### Local AIS / tracks

```text
MARINE_TRACK_AIS_CSV=/path/to/ais.csv
```

Формат CSV:

```text
mmsi,time,lon,lat,sog_knots,cog_deg
```

`mmsi`, `time`, `lon`, `lat` обязательны. `sog_knots`, `cog_deg` опциональны. Local AIS adapter входит в core и не требует provider extras.

### NOAA MarineCadastre

```text
NOAA_MARINECADASTRE_BASE_URL=
NOAA_MARINECADASTRE_CACHE_DIR=runs/noaa_ais
```

`NOAA_MARINECADASTRE_BASE_URL` должен указывать на директорию, в которой доступны годовые поддиректории с daily ZIP archives в формате `AIS_YYYY_MM_DD.zip`. URL не захардкожен в коде намеренно: если NOAA изменит структуру или используется локальное зеркало, достаточно изменить `.env`. Adapter входит в core и не требует provider extras.

## Проверка provider-аудита

```bash
MARINE_TRACK_PROVIDER_PROFILE=all python runtime_check.py
MARINE_TRACK_PROVIDER_PROFILE=core python runtime_check.py
python -m pytest -q
```

`runtime_check.py` проверяет импорты provider-модулей согласно `MARINE_TRACK_PROVIDER_PROFILE`, обязательные пути и числовые env-переменные. Provider preflight встроен в `deploy_telegram_bot.sh` и не делает внешние сетевые запросы.

## Политика проекта по провайдерам

1. Провайдер не добавляется в `config/sources.yaml`, если для него нет кода.
2. Провайдер не должен создавать фейковые raster assets. Если API возвращает только metadata/preview, detector должен честно отказаться от обработки.
3. Любой auth flow должен быть управляем через `.env`, без токенов в коде.
4. Если внешний API меняет endpoint, корректировка должна быть в `.env` или отдельном provider-классе, а не в detector pipeline.
5. Если provider package не установлен по выбранному профилю, runtime-check не должен валить core deployment; рабочие команды должны давать понятную ошибку при попытке использовать отсутствующий provider.
