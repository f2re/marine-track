# Провайдеры доступа Marine Track

Документ фиксирует только реально реализованные провайдеры. Источники без рабочего кода не должны попадать в `config/sources.yaml` priority.

## Provider dependency profiles

Provider-пакеты вынесены в optional extras. Это позволяет поставить все источники или сознательно пропустить тяжелые/неиспользуемые провайдеры.

```bash
# Все провайдеры: scene + auxiliary. Интерактивно спросит ключи активных providers.
bash install_with_providers.sh --providers all
bash deploy_with_providers.sh --providers all

# Неинтерактивно: ключи не спрашиваются, preflight покажет недостающие доступы.
bash install_with_providers.sh --providers all --yes
bash deploy_with_providers.sh --providers all --yes

# Только спутниковые scene providers: ASF/STAC/Planetary Computer/Sentinel Hub
bash install_with_providers.sh --providers scene

# Только auxiliary providers: Copernicus Marine плюс core AIS adapters
bash install_with_providers.sh --providers aux

# Только core, без provider-пакетов
bash install_with_providers.sh --providers core --yes
```

Профиль записывается в `.env` как `MARINE_TRACK_PROVIDER_PROFILE`. `runtime_check.py` читает `.env` и проверяет только выбранный набор provider modules. Если профиль `core`, scene/aux provider packages не требуются и runtime-check их не валит.

Соответствие extras:

| Profile | pip target | Проверяются runtime-check |
|---|---|---|
| `all` | `.[providers]` | core + scene + aux |
| `scene` | `.[scene-providers]` | core + scene |
| `aux` | `.[aux-providers]` | core + aux |
| `core` / `none` | `.` | only core |

## Интерактивная настройка ключей

`install_with_providers.sh` и `deploy_with_providers.sh` вызывают `provider_configure.py`. Он проходит по активным провайдерам выбранного профиля, показывает краткую инструкцию и предлагает заполнить недостающие значения в `.env`. Уже заполненные значения не перезаписываются.

Ручной запуск:

```bash
sudo python3 /opt/marine_track/provider_configure.py \
  --env-file /opt/marine_track/.env \
  --profile all

sudo chown root:marinetrack /opt/marine_track/.env
sudo chmod 0640 /opt/marine_track/.env
```

Проверка без сетевых запросов:

```bash
sudo -u marinetrack /opt/marine_track/.venv/bin/python /opt/marine_track/runtime_check.py
sudo -u marinetrack /opt/marine_track/.venv/bin/python /opt/marine_track/provider_preflight.py
```

`provider_preflight.py` падает только при отсутствии установленных provider-модулей, выбранных профилем. Отсутствующие ключи показываются как предупреждения, чтобы можно было поставить сервис заранее и добавить доступы позже.

## Scene providers

| Provider | Sensor | Код | Доступ | Примечание |
|---|---|---|---|---|
| `asf` | Sentinel-1 | `marine_track.data_sources.asf_provider.ASFProvider` | Search без ключа, download через NASA Earthdata | Возвращает ASF product ZIP/preview; ZIP не обрабатывается как GeoTIFF в MVP detection. |
| `copernicus_cdse` | Sentinel-1/2 | `marine_track.data_sources.stac_provider.STACProvider` | CDSE STAC, optional OAuth bearer | Поиск через `https://catalogue.dataspace.copernicus.eu/stac`. |
| `planetary_computer` | Sentinel-1 RTC, Sentinel-2 L2A | `STACProvider` | Public STAC; asset signing через `planetary-computer` | Основной provider для `/detectbbox`, когда нужны COG/GeoTIFF assets. |
| `earthsearch` | Sentinel-2 L2A | `STACProvider` | Public STAC | Только Sentinel-2. Sentinel-1/EarthSearch не включен в priority, чтобы не было ложной конфигурации. |
| `sentinelhub` | Sentinel-1/2 | `marine_track.data_sources.sentinelhub_provider.SentinelHubProvider` | OAuth client credentials или access token | Реальный Sentinel Hub Catalog API provider. Не создает фейковых raster assets; показывает только то, что вернул Catalog. |

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

Допустимые значения: `all`, `scene`, `aux`, `core`, `none`. Значение управляет только установкой/проверкой Python provider packages. Настройки доступа ниже всё равно можно хранить в `.env`; они будут использованы, когда соответствующий provider установлен.

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
CDSE_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
CDSE_USERNAME=
CDSE_PASSWORD=
```

Как получить: создать аккаунт Copernicus Data Space Ecosystem. Если `CDSE_ACCESS_TOKEN` задан, он используется как bearer token. Если заданы `CDSE_USERNAME` и `CDSE_PASSWORD`, код получает token через OAuth password grant. По умолчанию используется public client `cdse-public`; при необходимости можно задать собственный client id/secret.

### Planetary Computer

Дополнительные credentials не требуются. Для assets используется библиотека `planetary-computer`, которая подписывает URL при materialization. Для этого нужен профиль `all` или `scene`.

### EarthSearch

Дополнительные credentials не требуются. Используется публичный STAC endpoint Element84 EarthSearch v1. Для этого нужен профиль `all` или `scene`.

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
python provider_preflight.py
python -m pytest -q
```

`runtime_check.py` проверяет импорты provider-модулей согласно `MARINE_TRACK_PROVIDER_PROFILE`, обязательные пути и числовые env-переменные. Он не делает внешние сетевые запросы.

## Политика проекта по провайдерам

1. Провайдер не добавляется в `config/sources.yaml`, если для него нет кода.
2. Провайдер не должен создавать фейковые raster assets. Если API возвращает только metadata/preview, detector должен честно отказаться от обработки.
3. Любой auth flow должен быть управляем через `.env`, без токенов в коде.
4. Если внешний API меняет endpoint, корректировка должна быть в `.env` или отдельном provider-классе, а не в detector pipeline.
5. Если provider package не установлен по выбранному профилю, runtime-check не должен валить core deployment; рабочие команды должны давать понятную ошибку при попытке использовать отсутствующий provider.
