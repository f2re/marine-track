# План реализации Marine Track

План разделяет эксплуатационную надёжность, фактически реализованный single-raster MVP и научную валидацию. Пока release gate не закрыт, расширение алгоритмов и подключение новых источников не является приоритетом.

## Целевой результат текущего релиза

Telegram-бот и CLI должны по AOI/времени:

1. найти сцену с реально доступным GeoTIFF/COG;
2. сохранить полную provenance и effective processing config;
3. получить геопривязанные `vessel_candidate` с evidence features и quality flags;
4. показать optional wake evidence, не выдавая любой line feature за след;
5. выдать GeoJSON, CSV/Parquet, overview/crops и `report.json`;
6. вернуть понятную ошибку при отсутствии processable asset, а не «0 судов».

Оперативная скорость судна не входит в обязательный MVP. AIS SOG — внешний reference. Kelvin-wavelength результат — research-only proxy до отдельной валидации.

## Срез состояния на 2026-07-10

### Реализовано

- [x] Telegram-бот, главное меню, сохранённые AOI/bbox, пагинация сцен.
- [x] `/dates`, `/bboxdates`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`, `/output`.
- [x] scene registry с token/provider/sensor/assets/AOI geometry.
- [x] TTL scene-search cache и raster cache.
- [x] AOI crop и optional land/shoreline mask.
- [x] Single-band local-CFAR-style candidate detector.
- [x] connected components, площадь, форма, локальный контраст и геопривязанный pixel scale.
- [x] Canny/Hough wake-axis enrichment с явной 180° ambiguity.
- [x] local AIS CSV match, интерполяция track point и overlay.
- [x] GeoJSON/CSV/Parquet, overview/crops и `report.json`.
- [x] два эксплуатационных скрипта install/deploy, provider profiles и smoke-check.

### Реализовано, но только экспериментально

- [~] wake wavelength → Kelvin formula: не является валидированной скоростью и не должно быть основным пользовательским полем.
- [~] `confidence`: ranking score, не вероятность.
- [~] Hough wake: candidate line, не подтверждённый Kelvin/turbulent wake.
- [~] AIS: reference/matching layer, не независимая ground truth без контроля gaps, времени и качества.

### Не реализовано или не подключено

- [ ] Release gate: текущая ветка имеет 4 failing tests и 2 ruff import errors.
- [ ] Актуальный CDSE STAC v1 endpoint/collections и CDSE OData fallback.
- [ ] Единый provider contract для search-only/preview/raster/archive capabilities.
- [ ] Effective `config/processing.yaml` в CLI/Telegram pipeline.
- [ ] S1 calibration/unit contract, proper guard-cell CFAR, robust clutter model.
- [ ] S1 dual-polarization fusion и incidence-angle provenance.
- [ ] Wake mask/sector/arm/continuity/angle quality gates.
- [ ] Интеграция `validation.py`, explicit QC states и uncertainty.
- [ ] Copernicus Marine current/wave/wind context в detection report.
- [ ] Benchmark dataset, labels, fixed split и evaluation CLI.
- [ ] Sentinel-2 B02/B03/B04/B08 stack, SCL/cloud/water mask и optical detector.
- [ ] ASF SAFE/GRD materializer/processor.
- [ ] Raster cache lock-файлы и tiled inference с deduplication.
- [ ] HTML-отчёт; он не является требованием текущего MVP, пока нет отдельного UI scope.

## P0. Сначала восстановить release gate и данные

### P0.1. CI и контракт тестов

- [ ] Обновить stale tests под текущий контракт: alias `none` удалён, `check_smoke` API актуален, сообщения numeric validation синхронизированы.
- [ ] Исправить import order в `detection_pipeline.py` и `telegram_bot.py`.
- [ ] Сохранить regression test для нулевого background std: candidate не должен получать ложный положительный contrast без явного fallback-флага.
- [ ] Повторить `pytest -q`, `ruff check src tests`, `bash -n` обоих скриптов.

### P0.2. CDSE/провайдеры

- [ ] Вынести в env/config:
  - `CDSE_STAC_URL=https://stac.dataspace.copernicus.eu/v1/`;
  - Sentinel-1 collection `sentinel-1-grd`;
  - Sentinel-2 collection `sentinel-2-l2a`;
  - `CDSE_ODATA_URL=https://catalogue.dataspace.copernicus.eu/odata/v1/Products`.
- [ ] Добавить offline provider contract tests: endpoint, collection, datetime, AOI, asset media type, fallback.
- [ ] Реализовать OData fallback для случаев, когда STAC не индексирует сцену или не предоставляет processable asset.
- [ ] Уточнить Planetary Computer auth preflight: каталог может быть публичным, но S1 RTC asset требует SAS/account flow.
- [ ] Отделить `search_capable`, `preview_capable`, `raster_capable`, `archive_capable`.
- [ ] Синхронизировать `config/sources.yaml`, `detection_scene_search.py`, README и provider docs.

### P0.3. Честная модель результата

- [ ] Переименовать пользовательский смысл `confidence` в `evidence_score` до калибровки.
- [ ] Ввести `candidate_status`: `candidate`, `confirmed`, `rejected`, `ambiguous`.
- [ ] Ввести `quality_flags`, `ship_score`, `wake_score`, `quality_score`, `uncertainty`.
- [ ] По умолчанию `heading_method=not_estimated`, если wake geometry QC не пройден.
- [ ] По умолчанию `speed_method=not_estimated`; AIS SOG хранить как reference, Kelvin — как research proxy.

## P1. S1 baseline, на котором можно строить науку

### P1.1. Preprocessing и CFAR

- [ ] Зафиксировать units и calibration: DN/amplitude/sigma0/gamma0/dB в metadata.
- [ ] Применять S1-specific preprocessing, valid water mask и NaN/edge accounting.
- [ ] Заменить текущую схему на guard-cell CFAR: training ring отдельно от CUT/guard cells.
- [ ] Добавить robust clutter alternatives: quantile/MAD, gamma/K-distribution preset по scene context.
- [ ] Поддержать tiled inference, overlap merge и контроль duplicate detections.
- [ ] Калибровать thresholds по validation split, а не только по synthetic test.

### P1.2. Геометрия и wake

- [ ] Применять land mask и shoreline suppression и в detector, и в wake crop.
- [ ] Удалять border/edge lines и проверять valid-water fraction.
- [ ] Для каждой line hypothesis считать continuity, length, onset distance, sector behind vessel, local contrast.
- [ ] Отдельно искать central turbulent wake и Kelvin arms; не смешивать их признаки.
- [ ] Проверять arm symmetry, vertex proximity, angle residual и 180° ambiguity.
- [ ] Отдавать heading только через quality gate и хранить circular uncertainty.

### P1.3. AIS и ocean context

- [ ] Ввести max AIS interpolation gap, time uncertainty, image acquisition interval и match ambiguity.
- [ ] Хранить `ais_status`: `matched`, `unmatched`, `ambiguous`, `stale`, `out_of_window`.
- [ ] Интегрировать `validation.py` в pipeline; сохранять причины физического rejection.
- [ ] Подключить Copernicus Marine через явные dataset ids, units и temporal interpolation.
- [ ] Для wake/speed учитывать current vector, wave height/period, wind/sea-state и finite-depth flag.

## P1. Benchmark и оценка

- [ ] Собрать manifest сцен: product id, asset, sensor, polarization, orbit, incidence, GSD, wind/sea/depth context.
- [ ] Разметить ship body, candidate/no-candidate, wake axis/arms, optional length/heading.
- [ ] Сформировать negative scenes: sea clutter, coastline, port, offshore structures, clouds/glint.
- [ ] Разделить train/validation/test по сценам и проходам, не допуская утечки соседних кадров.
- [ ] Добавить baseline: current CFAR, improved guard-cell CFAR, optional classical wake detector.
- [ ] Добавить evaluation CLI и bootstrap confidence intervals.

### Метрики

- detection: precision, recall, F1, POD, FAR, CSI, false alarms/km², localization MAE/p95;
- wake: detection rate, false-wake rate, angular MAE/p95, continuity/arm quality;
- speed: bias, MAE, RMSE, median absolute error, coverage and uncertainty calibration against AIS/reference;
- operations: provider success, latency, cache hit rate, bytes downloaded, error class distribution.

Научная приемка — улучшение относительно baseline на независимом test split с доверительными интервалами. Фиксированные проценты качества не объявляются до pilot benchmark.

## P2. Sentinel-2 и расширение

- [ ] Реализовать B02/B03/B04/B08 stack с единым CRS/resolution.
- [ ] Добавить SCL/cloud/shadow/water/glint masks.
- [ ] Разделить optical detector и S1 detector; не использовать один threshold profile.
- [ ] Для inter-band speed учитывать реальные band time delays и геометрические corrections.
- [ ] Добавлять optical Kelvin-wave speed только при достаточном разрешении/числе волн и с uncertainty.

## P2. ASF и temporal tracking

- [ ] Реализовать SAFE/GRD materializer и документировать system dependency (SNAP/pyroSAR или эквивалент).
- [ ] Сохранять raw product checksum и processing version.
- [ ] Добавить multi-scene association только после стабильного single-scene detector.
- [ ] Lock-файлы для asset download и atomic cache manifest.

## Критерий перехода к ML

ML/нейросеть подключается только после:

1. зелёного engineering gate;
2. опубликованного data card/label schema;
3. classical baseline с метриками и error taxonomy;
4. fixed train/validation/test split;
5. проверки CPU/RAM/latency и преимуществ относительно baseline.

## Журнал

- 2026-07-06: создан MVP pipeline, providers, Telegram flow и initial docs.
- 2026-07-07: добавлены deployment/release gate, UX, caching, progress и output modes.
- 2026-07-08: добавлены AIS matching, tracks и overlays.
- 2026-07-09: добавлены shape/contrast/physical-scale metrics и experimental wake wavelength.
- 2026-07-10: проведён текущий audit; зафиксированы provider/data-access blockers, красный release gate, scientific scope и новая приоритизация.
