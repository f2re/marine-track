# Техническое задание: Marine Track MVP-0.2

## 1. Назначение и границы

Marine Track — воспроизводимый конвейер поиска спутниковых сцен и формирования геопривязанных **кандидатов судов** на морской акватории. До прохождения benchmark результат не называется гарантированной детекцией судна.

Обязательная цель MVP-0.2:

```text
AOI + UTC interval → processable raster scene → sensor-aware preprocessing → candidate objects → optional wake evidence → provenance/QC outputs
```

В MVP-0.2 не входят как подтверждённые продукты:

- глобальная realtime-система;
- классификация типа/размера судна с гарантированной точностью;
- оперативная скорость по одной сцене;
- ML-детектор без benchmark и baseline;
- Sentinel-2 multi-band stack до завершения S1 baseline;
- обработка ASF SAFE/GRD, пока не существует отдельного materializer/processor.

## 2. Входные данные

Система принимает:

- AOI GeoJSON в EPSG:4326; допускаются Polygon/MultiPolygon, Feature и FeatureCollection;
- `start/end` в UTC;
- sensor: `auto`, `sentinel1`, `sentinel2`;
- max results, cloud/polarization/beam filters;
- output/cache directories;
- optional AIS dataset и ocean-context dataset.

AOI должен быть валидирован до provider/download: finite coordinates, closed rings, geometry validity, допустимая площадь, число вершин и bbox aspect ratio. Лимиты площади, временного окна, `max_results`, скачиваемых байтов и времени обработки задаются конфигурацией и возвращаются в typed error. Antimeridian/полярные области должны либо поддерживаться явно, либо отклоняться с понятной ошибкой.

`start/end` обязаны быть timezone-aware UTC и входить в cache/provenance как абсолютные значения. Пустой интервал, `start >= end` и интервал сверх лимита отклоняются до обращения к provider.

## 3. Data/provider contract

### 3.1. Sentinel-1 — основной канал

Приоритет — processable GRD/RTC COG с provenance и единицами измерения. CDSE STAC contract:

```text
CDSE_STAC_URL=https://stac.dataspace.copernicus.eu/v1/
collection=sentinel-1-grd
```

Резервный поиск/скачивание:

```text
CDSE_ODATA_URL=https://catalogue.dataspace.copernicus.eu/odata/v1/Products
```

Planetary Computer S1 RTC/GRD используется как optional raster fallback при успешной авторизации/подписании asset. ASF в текущем MVP считается search/preview/archive provider до реализации SAFE/GRD processing.

### 3.2. Sentinel-2 — второй канал

Актуальная CDSE STAC collection:

```text
collection=sentinel-2-l2a
```

В полном optical pipeline требуются B02/B03/B04/B08, единый CRS/resolution, SCL/cloud/shadow/water mask и provenance по каждой полосе. До этого отдельный single-band asset не считается полноценной Sentinel-2 детекцией.

### 3.3. Auxiliary data

- local AIS — reference/validation;
- NOAA MarineCadastre — историческая AIS для US waters, не глобальный realtime;
- Copernicus Marine — currents/waves/wind/SST context, только с dataset id, units и temporal interpolation;
- Natural Earth — land/shoreline geometry, не замена точной water mask.

Провайдеры обязаны сообщать capability: `search`, `preview`, `raster`, `archive`, `auth_required`.

### 3.4. Typed asset contract

`SceneAsset` хранит как минимум:

```text
key, href, alternate_hrefs, media_type, roles, band/polarization,
units, scale, offset, nodata, raster_shape, auth_scheme,
expires_at, calibration/noise sidecars, checksum
```

Provider adapter не должен сводить STAC asset к строковому URL. Materializer выбирает asset по media type/roles/band/capability, выполняет auth-aware range-read canary, проверяет raster header и не сохраняет credentials/SAS/query tokens в logs/report/cache key.

Для CDSE смена endpoint должна сопровождаться обработкой amplitude COG, calibration/noise XML и auth/alternate references. Для Earth Search S1 `s3://` requester-pays asset является detection-capable только при успешном credential/cost preflight. ASF ZIP/SAFE остаётся archive-only до отдельного processor.

### 3.5. Search selection and cache contract

Search cache key включает:

```text
AOI canonical hash + start/end UTC + sensor + purpose/capability + filters
+ max_results + ordered provider/config fingerprint + cache schema version
```

Cache hit всегда повторно проходит capability, auth expiry и asset readability validation. `/dates` и `/detectbbox` не разделяют запись, если purpose различается. Результаты детерминированно сортируются по acquisition start/end, provider priority и product id; выбор «самой свежей» сцены не зависит от порядка ответа API.

## 4. Scene/provenance requirements

Каждая выбранная сцена должна сохранять:

- provider, endpoint/profile и collection;
- product id, acquisition start/end, orbit/platform, mode/polarization;
- selected asset key, media type, href scheme и download status;
- CRS, transform, width/height, GSD/pixel scale;
- band name, units/calibration level, nodata;
- AOI geometry/hash и факт crop;
- processing config, code commit и package/runtime versions.

Время хранится как acquisition start/end плюс заявленная uncertainty. Если сенсор/продукт допускает band/line/pixel time offsets, они сохраняются отдельно и учитываются в AIS/inter-band matching.

Preview, thumbnail и archive нельзя передавать detector как raster asset. При отсутствии processable asset pipeline возвращает typed error, а не пустой успешный результат. Provenance не содержит абсолютных server paths, bearer/SAS tokens, credentials или полный signed href; секреты удаляются централизованным sanitizer.

## 5. Preprocessing

### Sentinel-1

1. Проверить calibration/unit contract: DN/amplitude/sigma0/gamma0/dB.
2. Выполнить valid/nodata/water/land/shoreline mask.
3. Применить документированный speckle/clutter preset.
4. Работать в физически согласованной шкале, сохраняя исходные units.
5. Для больших raster использовать tiles/overlap и deterministic merge.

### Sentinel-2

1. Собрать B02/B03/B04/B08 и привести к единой сетке.
2. Исключить cloud, cirrus, shadow, invalid, land и glint pixels.
3. Сформировать optical features/ratios.
4. Не смешивать optical score с S1 score без sensor-specific calibration.

## 6. Candidate detector

В MVP допускается classical detector, но он должен быть честно описан как `vessel_candidate`.

Минимальный алгоритм S1:

1. robust local clutter estimate;
2. guard-cell CFAR или эквивалентный явно документированный robust threshold;
3. connected components;
4. min/max physical area, valid fraction и edge/shoreline rejection;
5. features объекта и evidence score;
6. tile-overlap deduplication.

Обязательные признаки:

- centroid, bbox, area/diameter;
- length/width, elongation, compactness, solidity;
- local CNR/background scale/peak;
- pixel scale/GSD и uncertainty;
- distance to land/AOI edge, water fraction;
- sensor/polarization/incidence/orbit metadata;
- detector parameter stability.

`evidence_score` — ranking feature. Поле `vessel_probability` появляется только после calibration split.

Полный целевой набор производных признаков и их units/QC определён в [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md). Detector не может использовать shape/wake feature, если его applicability gate не пройден.

## 7. Wake and heading

Wake analysis выполняется в отдельном water-only crop:

- suppress land, borders and nodata;
- find line hypotheses with Canny/Hough/Radon;
- test line length/continuity/contrast and vessel-relative sector;
- separately test central turbulent wake and Kelvin arms;
- compute arm/angle/vertex/symmetry residuals;
- return `wake_score`, QC flags and angular uncertainty.

Если direction cannot be resolved, `heading_deg` may contain an axis, но `heading_ambiguity_deg=180` и `heading_method` обязаны явно это отражать. При непрохождении QC курс не выдаётся.

## 8. Speed policy

По умолчанию:

```text
speed.value_knots=null
speed.method=not_estimated
```

### AIS

AIS SOG/COG — внешний reference. Сохраняются MMSI, position/time gap, distance, interpolation interval, number of points, assignment margin и match status. Matching ограничивает interpolation gap и выполняет one-to-one assignment: один MMSI не подтверждает несколько candidates. AIS не должен незаметно маскировать отсутствие собственной оценки.

### Sentinel-2 inter-band

Метод допустим только после учёта реальных band time delays, push-broom geometry, registration и subpixel matching. Он относится к optical research stage.

### Kelvin wavelength

Формула глубокой воды:

```text
V = sqrt(g * Lmax / (2*pi))
```

может использоваться только при подтверждённых transverse/Kelvin waves, достаточном числе разрешённых длин волн, проверке глубины/sea-state/current и наличии uncertainty. Текущий cross-axis peak estimator является research proxy:

```text
research_proxies.kelvin_speed_proxy_knots = ...
research_proxies.kelvin_speed_proxy_method = kelvin_wavelength_experimental
speed.value_knots = null
speed.method = not_estimated
```

До benchmark это поле не должно попадать в основной Telegram summary как оперативная скорость.

## 9. Validation

Статусы:

```text
unvalidated | matched | unmatched | ambiguous | stale | rejected_physics | confirmed
```

Физические проверки должны быть реально вызваны pipeline и сохранять причину:

- диапазон/uncertainty скорости;
- heading alignment с 180°-aware circular difference;
- wake geometry consistency;
- current/depth/sea-state applicability;
- AIS temporal/spatial quality.

## 10. Outputs

Обязательные:

- `detections.geojson` — Point features и свойства evidence/QC;
- `detections.csv` и `detections.parquet`;
- `overview.png` и candidate crops;
- `report.json` с provenance, effective config, errors, QC и artifact paths.

HTML-отчёт не является требованием MVP-0.2 и планируется отдельно после стабилизации JSON schema/UI.

Минимальное свойство candidate:

```json
{
  "detection_id": "S1_20260710_000001",
  "candidate_status": "candidate",
  "satellite": "sentinel1",
  "provider": "copernicus_cdse",
  "product_id": "...",
  "acquisition_start": "2026-07-10T08:13:20Z",
  "acquisition_end": "2026-07-10T08:13:22Z",
  "ship_evidence": {"ranking_score": 0.68, "model_version": "classical-s1-v2"},
  "wake_evidence": {"ranking_score": null, "applicable": false},
  "scene_quality": {"score": 0.71, "flags": ["single_pol", "no_ais"]},
  "position_uncertainty_m": null,
  "heading": {"axis_deg": null, "direction_deg": null, "ambiguity_deg": 180},
  "speed": {"value_knots": null, "method": "not_estimated", "uncertainty_knots": null},
  "research_proxies": {"kelvin_speed_proxy_knots": null},
  "reference": {"ais": null},
  "validation_status": "unvalidated",
  "quality_flags": ["single_band"]
}
```

## 11. Security and operations

1. Telegram authorization по умолчанию fail-closed. Пустой allowlist не делает bot публичным; public mode включается только явным флагом и предупреждением runtime check.
2. Scene tokens, user state, outputs и callback actions привязаны к user/chat owner; cross-user replay отклоняется и журналируется без раскрытия AOI/asset.
3. State/registry/cache manifests пишутся через lock + temporary file + fsync/atomic replace. Есть schema version, retention и recovery повреждённого state.
4. Применяются per-user rate/concurrency quotas и server limits по AOI area/vertices, interval, result count, bytes, RAM/disk/time.
5. Ошибки и provenance проходят secret/path redaction. Signed URL хранится только в памяти или защищённом краткоживущем cache.
6. Production deploy использует versioned root-owned read-only release и отдельные writable state/cache/output directories; переключение и rollback атомарны.
7. CI проверяет заявленные версии Python, clean constrained install, pytest, ruff, type-check baseline, shell syntax и offline provider contracts. License file соответствует package metadata.

## 12. Критерии приёмки

### Engineering

1. pytest/ruff/bash syntax/clean install/core runtime check проходят.
2. CDSE/PC/EarthSearch/ASF provider contracts покрыты offline tests; выбранные operational paths — live range-read canaries без утечки secrets.
3. Одни и те же `product_id + asset + config + code_commit` дают воспроизводимый результат.
4. Search cache различает абсолютный интервал и capability; cache hit повторно валидируется, а newest-scene selection детерминирован.
5. Cache/state writes atomic, concurrent duplicate download prevented.
6. Пустой Telegram allowlist не открывает operational commands; cross-user scene token replay отклоняется.
7. AOI/quota limits проверяются до provider/download и отражаются typed error.
8. При provider/materializer failure пользователь получает типизированную и очищенную от secrets причину.

### Scientific

1. Есть fixed scene manifest, label schema, negative scenes и spatial/temporal holdout.
2. Report публикует POD/FAR/CSI/precision/recall/F1, false alarms/km² и localization error.
3. Wake публикует detection/false-wake rate и angular error.
4. Speed публикует bias/MAE/RMSE/coverage only for applicable paired samples.
5. Метрики стратифицированы по sensor/polarization/incidence/wind/depth/coast/open sea/day-night.
6. Новая версия сравнивается с classical baseline и имеет confidence intervals.
