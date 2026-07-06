# Провайдеры доступа Marine Track

Документ фиксирует только реально реализованные провайдеры. Источники без рабочего кода не должны попадать в `config/sources.yaml` priority.

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

### ASF / NASA Earthdata

```text
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
EARTHDATA_TOKEN=
```

ASF search работает без credentials. Для скачивания продуктов нужен Earthdata Login: либо username/password, либо EDL token. Текущий detection pipeline не обрабатывает ASF ZIP/GRD как GeoTIFF.

### Copernicus Data Space Ecosystem

```text
CDSE_ACCESS_TOKEN=
CDSE_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
CDSE_USERNAME=
CDSE_PASSWORD=
```

Если `CDSE_ACCESS_TOKEN` задан, он используется как bearer token. Если заданы `CDSE_USERNAME` и `CDSE_PASSWORD`, код получает token через OAuth password grant. По умолчанию используется public client `cdse-public`; при необходимости можно задать собственный client id/secret.

### Planetary Computer

Дополнительные credentials не требуются. Для assets используется библиотека `planetary-computer`, которая подписывает URL при materialization.

### EarthSearch

Дополнительные credentials не требуются. Используется публичный STAC endpoint Element84 EarthSearch v1.

### Sentinel Hub

```text
SENTINELHUB_ACCESS_TOKEN=
SENTINELHUB_CLIENT_ID=
SENTINELHUB_CLIENT_SECRET=
SENTINELHUB_TOKEN_URL=https://services.sentinel-hub.com/auth/realms/main/protocol/openid-connect/token
SENTINELHUB_CATALOG_URL=https://services.sentinel-hub.com/api/v1/catalog/1.0.0/search
```

Если задан `SENTINELHUB_ACCESS_TOKEN`, он используется напрямую. Иначе нужны OAuth client id/secret. Для Copernicus Data Space Sentinel Hub services переопределите `SENTINELHUB_TOKEN_URL` и `SENTINELHUB_CATALOG_URL` на CDSE endpoints.

### Copernicus Marine

```text
COPERNICUSMARINE_SERVICE_USERNAME=
COPERNICUSMARINE_SERVICE_PASSWORD=
```

Если пользователь уже выполнил login через toolbox, username/password можно не задавать. Для server deployment лучше задать обе переменные в `.env`.

### Local AIS / tracks

```text
MARINE_TRACK_AIS_CSV=/path/to/ais.csv
```

Формат CSV:

```text
mmsi,time,lon,lat,sog_knots,cog_deg
```

`mmsi`, `time`, `lon`, `lat` обязательны. `sog_knots`, `cog_deg` опциональны.

### NOAA MarineCadastre

```text
NOAA_MARINECADASTRE_BASE_URL=
NOAA_MARINECADASTRE_CACHE_DIR=runs/noaa_ais
```

`NOAA_MARINECADASTRE_BASE_URL` должен указывать на директорию, в которой доступны годовые поддиректории с daily ZIP archives в формате `AIS_YYYY_MM_DD.zip`. URL не захардкожен в коде намеренно: если NOAA изменит структуру или используется локальное зеркало, достаточно изменить `.env`.

## Проверка provider-аудита

```bash
python runtime_check.py
python -m pytest -q
```

`runtime_check.py` проверяет импорты реализованных provider-модулей, обязательные пути и числовые env-переменные. Он не делает внешние сетевые запросы.

## Политика проекта по провайдерам

1. Провайдер не добавляется в `config/sources.yaml`, если для него нет кода.
2. Провайдер не должен создавать фейковые raster assets. Если API возвращает только metadata/preview, detector должен честно отказаться от обработки.
3. Любой auth flow должен быть управляем через `.env`, без токенов в коде.
4. Если внешний API меняет endpoint, корректировка должна быть в `.env` или отдельном provider-классе, а не в detector pipeline.
