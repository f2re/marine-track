# План реализации Marine Track Telegram detection

## Целевой результат

Telegram-бот должен по выбранной акватории и сроку отправлять:

1. общий снимок акватории с нанесенными точками/номерами судов;
2. отдельные crop-снимки судов со следом/треком, координатами и параметрами;
3. GeoJSON/CSV/Parquet с результатами детекции;
4. служебный отчет с provenance: provider, sensor, product_id, acquisition_time, assets, параметры обработки.

## Текущий статус

- [x] Telegram-бот с командами поиска сцен.
- [x] `/dates` и `/bboxdates` для сроков за последние 12 часов.
- [x] `/image <token>` и inline preview/quicklook.
- [x] `scene_registry.json` как точка привязки будущей детекции.
- [x] Базовая локальная raster-детекция для single-band GeoTIFF.
- [x] `/detect <token>`.
- [x] `/detectbbox ...` для поиска detection-capable GeoTIFF/COG сцены и запуска обработки.
- [x] Materializer: scene token → full-resolution raster asset.
- [x] AOI geometry в registry и crop raster по AOI.
- [x] Optional shoreline/land mask по GeoJSON.
- [x] Automatic land/shoreline mask builder из URL или локального ZIP/SHP/GeoJSON.
- [x] Провайдеры scene search: ASF, CDSE STAC, Planetary Computer, EarthSearch, Sentinel Hub Catalog.
- [x] Auxiliary providers: Copernicus Marine toolbox, local AIS CSV, NOAA MarineCadastre archive adapter.
- [x] Provider dependencies вынесены в extras: `scene-providers`, `aux-providers`, `providers`.
- [x] Provider-aware wrappers: `install_with_providers.sh`, `deploy_with_providers.sh`.
- [x] Интерактивный запрос ключей/путей providers через `provider_configure.py`.
- [x] Provider preflight без сетевых вызовов через `provider_preflight.py`.
- [x] Runtime-check учитывает `MARINE_TRACK_PROVIDER_PROFILE` и не валит core-only deployment.
- [x] Overview PNG с точками судов.
- [x] Crop PNG по каждому судну.
- [x] Detection metadata сохраняется в модели, GeoJSON/report output и Telegram pipeline.
- [ ] Wake association вокруг каждого судна.
- [ ] AIS track rendering.

## Реализация по этапам

### Этап 1. Detection skeleton по token

- [x] `scene_materializer.py`: выбор GeoTIFF/COG asset из scene registry.
- [x] `detection_pipeline.py`: token → raster → detections → output files.
- [x] `rendering/overview.py`: общий PNG с точками судов.
- [x] `rendering/vessel_crop.py`: crop PNG по каждому судну.
- [x] Telegram `/detect <token>` и callback `mtdetect:<token>`.
- [x] Тесты materializer/pipeline/rendering.

Ограничение этапа: обрабатываются только raster assets, которые можно открыть как GeoTIFF/COG. ASF ZIP/GRD не обрабатывается как GeoTIFF и должен давать понятную ошибку.

### Этап 2. Sentinel-1 RTC path

- [x] Предпочитать Planetary Computer `sentinel-1-rtc` для `/detectbbox`.
- [x] VV/VH asset selection на уровне ключей GeoTIFF/COG.
- [x] AOI crop.
- [x] shoreline/land mask как опциональный GeoJSON-файл.
- [x] local CFAR.
- [x] автоматическое скачивание/обновление coastline/land mask через `marine-track update-land-mask`.

### Этап 3. Sentinel-2 optical path

- [x] Detection-capable STAC search для Sentinel-2 GeoTIFF/COG assets.
- [x] Sentinel Hub Catalog provider как metadata/search provider.
- [ ] B02/B03/B04/B08 asset selection как полноценный band stack.
- [ ] RGB/NIR composite.
- [ ] SCL/cloud mask.
- [ ] water mask.
- [x] bright object detector на single-band/visual GeoTIFF через local CFAR.

### Этап 4. Wake/track enrichment

- [ ] Crop around vessel.
- [ ] Hough/Radon wake axis association.
- [ ] Heading estimation from wake axis.
- [x] Local AIS CSV adapter.
- [x] NOAA MarineCadastre daily ZIP adapter with configured base URL.
- [ ] AIS track line rendering around acquisition time.
- [ ] Per-vessel crop overlay.

### Этап 5. Reporting

- [x] Telegram summary message.
- [x] Documents: GeoJSON, CSV, Parquet, report JSON.
- [x] Limit crop count by confidence if detections are many.
- [x] Detection metadata сохранена в `VesselDetection` и `to_geojson_feature()`.

### Этап 6. Provider access audit and deployment profiles

- [x] ASF provider implemented via `asf_search`.
- [x] CDSE STAC provider supports optional OAuth bearer token.
- [x] Planetary Computer provider implemented via STAC and signed assets.
- [x] EarthSearch provider implemented for Sentinel-2 L2A only.
- [x] Sentinel Hub Catalog provider implemented via OAuth Catalog API.
- [x] Copernicus Marine provider implemented via official toolbox.
- [x] Active provider list in `config/sources.yaml` matches implemented code.
- [x] Provider dependencies split into optional extras: `scene-providers`, `aux-providers`, `providers`.
- [x] Install/deploy scripts support `--providers all|scene|aux|core|none`.
- [x] Provider-aware wrappers run key configuration, extras install, runtime-check and provider-preflight.
- [x] Runtime-check imports provider modules according to `MARINE_TRACK_PROVIDER_PROFILE`.
- [x] Provider access documentation added to `docs/PROVIDERS.md`, README and Telegram instructions.

## Журнал прогресса

- 2026-07-06: создан план реализации; старт этапа 1.
- 2026-07-06: реализованы `scene_materializer.py`, `detection_pipeline.py`, `rendering/overview.py`, `rendering/vessel_crop.py`; следующий шаг — подключение Telegram `/detect` и тесты.
- 2026-07-06: подключены Telegram `/detect <token>` и callback `mtdetect:<token>`; кнопка `🔎 Детекция` добавлена к срокам; добавлены тесты сквозного detection pipeline на synthetic GeoTIFF.
- 2026-07-06: AOI GeoJSON сохраняется в registry, materializer делает crop raster по AOI с reprojection; добавлен detection-capable STAC search и команда `/detectbbox`.
- 2026-07-06: detector переключен на local-CFAR style режим с `local_window_px`/`guard_window_px`; параметры detector-а пишутся в metadata детекций и `report.json`; README и Telegram-инструкции актуализированы.
- 2026-07-06: добавлен optional land/shoreline mask по GeoJSON в EPSG:4326; маска перепроецируется в CRS растра, буферизуется и применяется до normalizing/CFAR; настройки добавлены в `.env.example`, runtime-check и документацию.
- 2026-07-06: проведен provider-аудит; реализован Sentinel Hub Catalog provider, CDSE OAuth helper, Copernicus Marine toolbox provider, local AIS CSV adapter, NOAA MarineCadastre archive adapter; активный `sources.yaml` очищен от несуществующих priority provider-связок.
- 2026-07-06: исправлено сохранение metadata в `VesselDetection`; Telegram detection pipeline переведен на keyword-аргументы; runtime-check расширен на AIS provider modules; добавлены тесты provider auth, Sentinel Hub mapping и detection metadata.
- 2026-07-06: provider dependencies вынесены в optional extras; install/deploy получили `--providers all|scene|aux|core|none`; `.env` синхронизирует `MARINE_TRACK_PROVIDER_PROFILE`; runtime-check стал profile-aware и поддерживает core-only deployment без provider packages.
- 2026-07-06: добавлены `provider_configure.py`, `provider_preflight.py`, `install_with_providers.sh`, `deploy_with_providers.sh`; интерактивные wrapper-скрипты запрашивают ключи/пути активных providers, устанавливают выбранные extras, запускают runtime/preflight и затем стартуют/перезапускают сервис.
- 2026-07-06: добавлен `land_mask_update.py` и CLI-команда `marine-track update-land-mask`; поддержаны URL, локальный ZIP/SHP/GeoJSON, cache, force rebuild и AOI clipping; `.env.example`, README, runtime-check и тесты обновлены.
