# Оперативные источники данных и библиотеки доступа

## 1. Sentinel-1 SAR — основной канал MVP

### NASA ASF

Назначение: поиск и загрузка Sentinel-1 SAR сцен.

Библиотека: `asf_search`.

Использование в проекте: `marine_track.data_sources.asf_provider.ASFProvider`.

Плюсы:

- удобный Python API;
- поддержка поиска по AOI;
- поддержка Sentinel-1;
- удобная загрузка продуктов.

Ограничения:

- для скачивания часто нужны Earthdata credentials или token;
- для production надо явно управлять `.netrc`/token.

### Copernicus Data Space Ecosystem

Назначение: основной европейский доступ к Sentinel-данным.

Доступ:

- STAC;
- OData;
- S3;
- Sentinel Hub API;
- openEO.

Библиотеки:

- `pystac-client`;
- `sentinelhub`;
- `requests` для OData;
- `openeo` как отдельный вариант.

Использование в проекте: `STACProvider(name="copernicus_cdse")`.

## 2. Sentinel-2 optical/MSI — второй канал MVP

Назначение:

- белая вода;
- альбедо-аномалия;
- оптический след;
- межканальное смещение судна;
- Kelvin wake при хорошей видимости.

Доступ:

- CDSE STAC/OData/Sentinel Hub;
- Microsoft Planetary Computer;
- EarthSearch.

Библиотеки:

- `pystac-client`;
- `planetary-computer`;
- `sentinelhub`;
- `stackstac`, `xarray`, `rioxarray` для последующей обработки.

## 3. Вспомогательная океанография

### Copernicus Marine

Назначение:

- течение;
- температура поверхности моря;
- волны;
- ветер;
- условия сохранения следа.

Библиотека: `copernicusmarine`.

Использование в MVP: источник для коррекции скорости относительно воды и для физической валидации.

## 4. AIS для валидации

### Локальный AIS

Лучший вариант для near-real-time в береговой зоне. Данные не зависят от внешних агрегаторов.

Библиотеки:

- `pyais`;
- `pandas`;
- `geopandas`.

### NOAA MarineCadastre

Хороший бесплатный исторический источник AIS для США. Используется для тестов и методической валидации, не для глобального realtime.

### Global Fishing Watch

Глобальные публичные продукты полезны для исследований, но не заменяют realtime AIS. Используются как дополнительный слой валидации.

## 5. Порядок подключения в коде

1. Сначала реализуется поиск сцен и provenance.
2. Потом загрузка/кэширование сцен.
3. Потом raster preprocessing.
4. Потом детекция.
5. Потом AIS/cross-sensor validation.

Ключевое правило: каждый результат должен содержать `provider`, `product_id`, `acquisition_time`, `processing_config` и `validation_status`.
