# План реализации Marine Track Telegram detection

## Release strategy

Первичный приоритет проекта теперь — не расширение алгоритмов, а надежный запуск и проверяемая эксплуатация Telegram-бота. Release gate вынесен в `docs/RELEASE_GATE.md`.

Пока release gate v0.1 не закрыт на сервере, не добавлять новые providers, Sentinel-2 full stack и ASF ZIP/GRD processing.

## Целевой результат

Telegram-бот должен по выбранной акватории и сроку отправлять:

1. общий снимок акватории с нанесенными точками/номерами судов;
2. отдельные crop-снимки судов со следом/треком, координатами и параметрами;
3. GeoJSON/CSV/Parquet с результатами детекции;
4. служебный отчет с provenance: provider, sensor, product_id, acquisition_time, assets, параметры обработки.

## Текущий статус

- [x] Telegram-бот с командами поиска сцен.
- [x] `/dates`, `/bboxdates`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`.
- [x] `scene_registry.json` как точка привязки детекции.
- [x] Базовая локальная raster-детекция для single-band GeoTIFF.
- [x] Улучшенная локальная CFAR-детекция: local contrast, shape metrics, physical scale, confidence provenance.
- [x] Документирована методика `docs/DETECTION_METHOD.md`.
- [x] TTL-кеш поиска сцен по AOI/sensor/lookback/max_results.
- [x] Общий raster cache по provider/product/asset/AOI.
- [x] Cleanup старых кешей и output-файлов по retention.
- [x] AOI geometry в registry и crop raster по AOI.
- [x] Optional shoreline/land mask по GeoJSON.
- [x] Automatic land/shoreline mask builder.
- [x] Провайдеры scene search: ASF, CDSE STAC, Planetary Computer, EarthSearch, Sentinel Hub Catalog.
- [x] Auxiliary providers: Copernicus Marine toolbox, local AIS CSV, NOAA MarineCadastre archive adapter.
- [x] Provider dependencies вынесены в extras: `scene-providers`, `aux-providers`, `providers`.
- [x] Единственные поддерживаемые shell-скрипты: `install_telegram_bot.sh` и `deploy_telegram_bot.sh`.
- [x] `deploy_telegram_bot.sh` содержит provider preflight, Telegram token prompt/healthcheck, command registration, land mask once-on-deploy и cleanup.
- [x] Runtime-check учитывает `MARINE_TRACK_PROVIDER_PROFILE`.
- [x] Убран compatibility-layer: `BOT_TOKEN`, provider-profile `none`, legacy `last_bbox` schema, `/bboxlist` alias.
- [x] Overview PNG с точками судов.
- [x] Crop PNG по каждому судну.
- [x] Detection metadata сохраняется в модели, GeoJSON/report output и Telegram pipeline.
- [x] Wake association вокруг каждого судна.
- [x] Wake wavelength experimental speed enrichment.
- [x] AIS validation/enrichment: MMSI, distance, SOG/COG, AIS track points, overlay на overview/crop.
- [x] Несколько сохраненных пользовательских bbox/AOI.
- [x] Пагинация списка сцен в Telegram без повторного provider search при перелистывании.
- [x] First-run hardening install/deploy: env lifecycle, healthcheck, provider preflight, runtime dirs, land mask preservation.
- [x] Локальный smoke-check без запуска Telegram polling.
- [x] Progress states для долгих операций: search/materialize/detect/render/send.
- [x] Режим “только картинки / только файлы / всё”.
- [ ] Lock-файлы для конкурентного скачивания одного raster asset.

## Этап 1. Release readiness

- [x] Два эксплуатационных shell-скрипта: install и deploy.
- [x] Runtime-check для core/provider profiles.
- [x] Provider preflight как Python-модуль без сетевых запросов.
- [x] Telegram healthcheck до restart.
- [x] Command registration до restart.
- [x] Сохранение generated land mask между deploy.
- [x] Writable runtime dirs для output/cache/state.
- [x] Локальный smoke-check.
- [ ] Фактический прогон release gate на сервере.

## Этап 2. Telegram UX

- [x] Главное меню `/start` и `/menu`.
- [x] Быстрый сценарий `Найти суда`: default AOI → fresh scene → detection.
- [x] Несколько сохраненных bbox/AOI per-user.
- [x] Dedup одинаковых bbox и лимит количества сохраненных районов.
- [x] `/areas` и `Мои районы` с действиями детекции, сроков и удаления.
- [x] Пагинация `/dates` и `/bboxdates` по сохраненному `scenes_json`.
- [x] Короткие callback_data для районов и страниц.
- [x] Progress states для long-running pipeline: search/materialize/detect/render/send.
- [x] Режим выдачи “только картинки / только файлы / всё”.

## Этап 3. Cache lifecycle and API minimization

- [x] Единая политика cache dirs, TTL, retention, cleanup.
- [x] TTL-кеш provider scene search.
- [x] Общий raster cache по product/asset/AOI.
- [x] Land mask once-on-deploy and cleanup.
- [x] CLI `marine-track cleanup-cache`.
- [x] Кеширование `/dates`, `/bboxdates`, `/detectbbox`.
- [ ] Lock-файлы для конкурентного скачивания одного asset несколькими процессами.

## Этап 4. Provider and deployment contracts

- [x] ASF provider via `asf_search`.
- [x] CDSE STAC provider.
- [x] Planetary Computer provider.
- [x] EarthSearch provider.
- [x] Sentinel Hub Catalog provider.
- [x] Copernicus Marine provider.
- [x] Active provider list in `config/sources.yaml` matches implemented code.
- [x] Provider dependencies split into optional extras.
- [x] Current provider profiles: `all|scene|aux|core`.
- [x] Removed profile alias `none`.
- [x] Removed Telegram token fallback `BOT_TOKEN`.

## Этап 5. Detection quality backlog

- [x] Local CFAR object extraction.
- [x] Physical pixel scale and object geometry in meters.
- [x] Local contrast/background provenance.
- [x] Shape metrics: major/minor axis, orientation, elongation.
- [x] Hough wake axis association.
- [x] Heading estimation from wake axis с 180° ambiguity flag.
- [x] Wake wavelength experimental speed enrichment.
- [x] Local AIS CSV adapter.
- [x] NOAA MarineCadastre daily ZIP adapter.
- [x] AIS track line rendering around acquisition time.
- [x] Per-vessel crop AIS overlay.
- [x] AIS SOG/COG as external speed/heading reference.
- [ ] Sentinel-2 B02/B03/B04/B08 asset selection as band stack.
- [ ] Sentinel-2 RGB/NIR composite.
- [ ] Sentinel-2 SCL/cloud/water mask.
- [ ] ASF ZIP/GRD processing через SNAP/pyroSAR.

## Журнал прогресса

- 2026-07-06: создан план реализации; старт MVP detection pipeline.
- 2026-07-06: реализованы materializer, detection pipeline, overview/crop rendering и Telegram `/detect`.
- 2026-07-06: добавлен `/detectbbox`, AOI crop, local CFAR, land/shoreline mask и automatic land mask builder.
- 2026-07-06: проведен provider-аудит; реализованы Sentinel Hub Catalog, CDSE OAuth helper, Copernicus Marine, local AIS и NOAA MarineCadastre adapter.
- 2026-07-06: provider dependencies вынесены в optional extras; install/deploy получили provider profiles.
- 2026-07-06: реализован cache lifecycle: TTL scene-search cache, общий raster cache, cleanup, Telegram/report cache status.
- 2026-07-06: установка и деплой консолидированы в два shell-скрипта.
- 2026-07-07: добавлены несколько сохраненных bbox/AOI per-user, `/areas`, `Мои районы` и пагинация списка сцен без нового provider search.
- 2026-07-07: усилен первый запуск на сервере: land mask preservation, writable runtime dirs, healthcheck before restart, command registration, smoke-check.
- 2026-07-07: удалены compatibility-хвосты `BOT_TOKEN`, profile alias `none`, legacy `last_bbox` и `/bboxlist`; provider preflight вынесен в текущий Python-модуль.
- 2026-07-07: добавлены progress states для Telegram detection flow: search, materialize, detect, render, send.
- 2026-07-07: добавлен per-user режим выдачи результата: картинки, файлы или всё; детекция отправляет только выбранные артефакты.
- 2026-07-07: начата научная составляющая: AIS validation/enrichment, external SOG/COG reference и AIS-track overlay на overview/crop.
- 2026-07-07: улучшен detector: shape metrics, local contrast, physical scale in meters, documented detection method.
- 2026-07-07: добавлена экспериментальная оценка скорости по wake wavelength с сохранением provenance в metadata.wake.wavelength.
