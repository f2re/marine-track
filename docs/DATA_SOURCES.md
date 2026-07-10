# Источники данных Marine Track и их реальные возможности

Документ разделяет discovery, preview, processable raster, archive и validation. Наличие записи в каталоге само по себе не означает, что detector сможет прочитать raster.

## 1. Sentinel-1 SAR — primary

### CDSE STAC v1

Актуальный endpoint:

```text
https://stac.dataspace.copernicus.eu/v1/
```

Основная collection для MVP:

```text
sentinel-1-grd
```

Документация: [CDSE STAC](https://documentation.dataspace.copernicus.eu/APIs/STAC.html), [Sentinel-1 GRD collection](https://stac.dataspace.copernicus.eu/v1/collections/sentinel-1-grd).

Старый `https://catalogue.dataspace.copernicus.eu/stac` deprecated с 17 ноября 2025 года и не должен оставаться hard-coded fallback.

Практические ограничения:

- STAC является complementary catalogue с ограниченным набором коллекций;
- asset может требовать CDSE authentication;
- нужно проверять media type, COG/GeoTIFF, polarization, units и actual readable href;
- при пропуске/задержке индексации использовать OData fallback.

### CDSE OData

```text
https://catalogue.dataspace.copernicus.eu/odata/v1/Products
```

Документация: [CDSE OData](https://documentation.dataspace.copernicus.eu/APIs/OData.html).

Использование: поиск и скачивание полного продукта, когда STAC item/asset отсутствует или непригоден. OData не отменяет необходимость отдельного SAFE/GRD processor.

### Planetary Computer

Collections: Sentinel-1 RTC и GRD. Dataset pages: [S1 RTC](https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc), [S1 GRD](https://planetarycomputer.microsoft.com/dataset/sentinel-1-grd).

STAC поиск публичен, но S1 RTC asset требует Planetary Computer account/API flow для SAS token. Это нужно проверять preflight-ом; текущая формулировка «credentials не требуются» неверна для operational materialization.

Planetary Computer удобен как fallback для COG/RTC, но нужно хранить способ подписания URL и срок действия токена. Не сохранять SAS token в provenance/report.

### NASA ASF

`asf_search` удобен для Sentinel-1 metadata/search и Earthdata download. Текущий код получает preview/product URL, но materializer сознательно не обрабатывает ASF ZIP/GRD. Поэтому ASF сейчас `search/preview/archive`, а не detection-capable provider.

SAFE/GRD processing — отдельный этап после стабильного COG baseline; он требует явного контракта калибровки, orbit/noise handling и системных зависимостей.

## 2. Sentinel-2 optical — secondary

Актуальная CDSE collection:

```text
sentinel-2-l2a
```

Ссылка: [CDSE Sentinel-2 L2A collection](https://stac.dataspace.copernicus.eu/v1/collections/sentinel-2-l2a).

Для scientific detector требуются:

- B02/B03/B04/B08;
- единый CRS/resolution;
- SCL/cloud/cirrus/shadow/water/glint masks;
- band time delays и push-broom geometry для inter-band speed;
- optical-specific threshold/feature model.

Пока pipeline читает один выбранный raster band, Sentinel-2 остаётся partial capability и не должен смешиваться с S1 confidence.

Дополнительные STAC sources: Planetary Computer, EarthSearch. Sentinel Hub — OAuth Catalog/Process provider; доступность, quota и наличие direct COG нужно проверять отдельно.

## 3. Ocean context

[Copernicus Marine Data Store](https://data.marine.copernicus.eu/products) предоставляет свободные/open продукты для currents, waves, wind/SST и global/regional ocean state.

Для использования в Marine Track требуется сохранять:

- dataset id и product version;
- variables/units;
- spatial/temporal interpolation method;
- valid time relative to satellite acquisition;
- missing/out-of-domain flag.

До подключения к detection/validation это только доступный wrapper, не используемый физический correction.

## 4. AIS validation

### Local AIS

Основной воспроизводимый reference для тестов. Нормализованный CSV:

```text
mmsi,time,lon,lat,sog_knots,cog_deg
```

Для match обязательно хранить time gap, spatial distance, interpolation gap, number of points и ambiguity.

### NOAA MarineCadastre

[MarineCadastre AIS](https://hub.marinecadastre.gov/) — authoritative historical US-focused source, полезный для retrospective validation; это не глобальный realtime stream.

### Global Fishing Watch

Может быть полезен как отдельный исследовательский источник, но в текущем коде provider не реализован и не должен числиться рабочим fallback.

## 5. Static geometry

Natural Earth land polygons подходят как coarse land/shoreline mask. Для nearshore detection следует учитывать геометрическую ошибку береговой линии, buffer sensitivity и не трактовать mask как точную линию воды.

## 6. Минимальный provenance contract

Каждый результат должен содержать:

```text
provider, endpoint/profile, collection, product_id, acquisition_start/end,
asset_key, media_type, href_scheme, CRS, GSD/pixel scale, band, units,
polarization, orbit/mode, AOI hash, processing_config, code_commit,
validation_status, quality_flags
```

Preview-only, archive-only и authentication failure должны быть отдельными состояниями, а не превращаться в пустой список детекций.
