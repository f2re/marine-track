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
- [ ] Корректный search cache: текущий key не содержит абсолютные start/end и capability; `/dates` может загрязнить `/detectbbox` cache.
- [ ] Fail-closed Telegram auth, user-scoped scene tokens, quotas и atomic state writes.
- [ ] Актуальный CDSE STAC v1 endpoint/collections и CDSE OData fallback.
- [ ] Typed asset/auth contract для search-only/preview/raster/archive capabilities и CDSE sidecars/alternates.
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

## P0. Сначала исправить correctness, access и пользовательскую семантику

### P0.1. Search/cache correctness

- [ ] Включить в cache key canonical AOI hash, абсолютные `start/end` UTC, sensor, purpose/capability, filters, `max_results`, ordered provider/config fingerprint и schema version.
- [ ] Разделить search-only `/dates` и detection-capable `/detectbbox`; при cache hit повторно проверять capability, auth expiry и raster readability.
- [ ] Детерминированно сортировать сцены по acquisition time, provider priority и product id; зафиксировать tie-breaker.
- [ ] Добавить regression tests для сдвинутых окон одинаковой длительности, cross-capability cache pollution, expired signed URL и provider-order change.

### P0.2. Access control, resource limits и честный UI/schema

- [ ] Сделать Telegram authorization fail-closed при пустом `TELEGRAM_ADMIN_IDS`; public mode разрешать только отдельным explicit flag.
- [ ] Привязать scene token, callbacks и output directory к owner user/chat; добавить cross-user replay tests.
- [ ] Ввести limits: AOI area/vertices/aspect, interval, `max_results`, download bytes, disk/RAM/time, per-user rate/concurrency.
- [ ] Заменить `vessels`, `Судно`, `conf` на candidate/evidence labels до benchmark.
- [ ] Разделить `speed.value_knots=null`, `research_proxies.kelvin_speed_proxy_knots` и `reference.ais.sog_knots`; не перезаписывать поля друг другом.
- [ ] Централизованно удалять bearer/SAS/query secrets, credentials и абсолютные local paths из errors/logs/report.

### P0.3. Typed provider/asset contract

- [ ] Ввести `SceneAsset`: href/alternates, media type, roles, band/polarization, units/scale/offset/nodata, shape, auth scheme/expiry, sidecars и checksum.
- [ ] Вынести в env/config CDSE STAC v1, `sentinel-1-grd`, `sentinel-2-l2a` и OData endpoint.
- [ ] Поддержать CDSE bearer/alternate/S3 access и calibration/noise sidecars; не считать миграцию законченной одной заменой URL.
- [ ] Добавить auth-aware range-read canary и typed failure до полного скачивания.
- [ ] Уточнить Planetary Computer catalog-vs-asset preflight; для Earth Search S1 учитывать `s3://` requester-pays credentials/cost.
- [ ] Оставить ASF `search/preview/archive` до SAFE/GRD processor.
- [ ] Добавить offline contract fixtures и минимальные live canaries для выбранных operational provider paths.

### P0.4. CI и воспроизводимый runtime contract

- [ ] Обновить stale tests под текущий контракт: alias `none` удалён, `check_smoke` API актуален, сообщения numeric validation синхронизированы.
- [ ] Исправить import order в `detection_pipeline.py` и `telegram_bot.py`.
- [ ] Сохранить regression test для нулевого background std: candidate не должен получать ложный положительный contrast без явного fallback-флага.
- [ ] Ввести `mypy` baseline: отделить optional dependency/stub debt от реальных type errors и запрещать рост числа ошибок.
- [ ] Проверять все заявленные Python versions, clean constrained install и dependency update job; добавить constraints/lock strategy.
- [ ] Добавить `LICENSE`, соответствующий metadata, и проверить sdist/wheel/runtime install.
- [ ] Повторить `pytest -q`, `ruff check src tests`, `mypy`, `bash -n`, build/install и core runtime check.

## P1-A. Воспроизводимость и эксплуатационная основа

### P1-A.1. Effective config и provenance

- [ ] Сделать `config/processing.yaml` и `config/sources.yaml` единственным versioned baseline; env/CLI overlays формируют один validated effective config.
- [ ] Применять одинаковые detector/provider filters и priorities в CLI и Telegram.
- [ ] Писать sanitized manifest: code commit, config hash/effective values, package/runtime versions, scene timing, collection/asset/auth mode, CRS/transform/GSD/band/units, AOI hash и errors.
- [ ] Не сохранять signed href, secrets, AIS local path и server absolute artifact paths.

### P1-A.2. Mask, state, cache и deploy

- [ ] Хранить versioned global coastline и строить AOI tile/subset cache, а не одну mask только для default AOI.
- [ ] Делать shoreline buffer в metric/geodesic geometry; использовать explicit valid-data/water mask.
- [ ] Сделать registry/user-state/cache manifests atomic и locked; добавить schema migration, corruption recovery и полный retention для `dates_*`, `bboxdates_*`, `detectbbox_*`, previews/registry.
- [ ] Перевести production deploy на versioned root-owned read-only releases, отдельные writable state/cache/output dirs, pre-switch checks, atomic switch и rollback.

## P1-B. S1 baseline, на котором можно строить науку

Целевые formulas/units/QC для object, wake, environment и AIS fields зафиксированы в [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md).

### P1-B.1. Preprocessing и CFAR

- [ ] Зафиксировать units и calibration: DN/amplitude/sigma0/gamma0/dB в metadata.
- [ ] Применять S1-specific preprocessing, valid water mask и NaN/edge accounting.
- [ ] Заменить текущую схему на guard-cell CFAR: training ring отдельно от CUT/guard cells.
- [ ] Добавить robust clutter alternatives: quantile/MAD, gamma/K-distribution preset по scene context.
- [ ] Поддержать tiled inference, overlap merge и контроль duplicate detections.
- [ ] Калибровать thresholds по validation split, а не только по synthetic test.

### P1-B.2. Геометрия и wake

- [ ] Применять land mask и shoreline suppression и в detector, и в wake crop.
- [ ] Удалять border/edge lines и проверять valid-water fraction.
- [ ] Для каждой line hypothesis считать continuity, length, onset distance, sector behind vessel, local contrast.
- [ ] Отдельно искать central turbulent wake и Kelvin arms; не смешивать их признаки.
- [ ] Проверять arm symmetry, vertex proximity, angle residual и 180° ambiguity.
- [ ] Отдавать heading только через quality gate и хранить circular uncertainty.

### P1-B.3. AIS и ocean context

- [ ] Ввести max AIS interpolation gap, time uncertainty, image acquisition interval и match ambiguity.
- [ ] Выполнять one-to-one candidate↔AIS assignment и antimeridian-safe interpolation; хранить first/second match margin.
- [ ] Хранить `ais_status`: `matched`, `unmatched`, `ambiguous`, `stale`, `out_of_window`.
- [ ] Интегрировать `validation.py` в pipeline; сохранять причины физического rejection.
- [ ] Подключить Copernicus Marine через явные dataset ids, units и temporal interpolation.
- [ ] Для global baseline зафиксировать variables из PHY `GLOBAL_ANALYSISFORECAST_PHY_001_024` и WAV `GLOBAL_ANALYSISFORECAST_WAV_001_027`; для регионов разрешать versioned product override.
- [ ] Добавить GEBCO 2026 AOI bathymetry subset и provenance для finite-depth applicability.
- [ ] Для wake/speed учитывать current vector, wave height/period, wind/sea-state и finite-depth flag.

## P1-C. Benchmark и оценка

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
