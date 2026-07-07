# План реализации Marine Track Telegram detection

## Целевой результат

Telegram-бот должен по выбранной акватории и сроку отправлять:

1. общий снимок акватории с нанесенными точками/номерами судов;
2. отдельные crop-снимки судов со следом/треком, координатами и параметрами;
3. GeoJSON/CSV/Parquet с результатами детекции;
4. служебный отчет с provenance: provider, sensor, product_id, acquisition_time, assets, параметры обработки.

## Текущий статус

- [x] Telegram-бот с командами поиска сцен.
- [x] `/dates`, `/bboxdates`, `/image`, `/detect`, `/detectbbox`, `/status`, `/whoami`.
- [x] `scene_registry.json` как точка привязки будущей детекции.
- [x] Базовая локальная raster-детекция для single-band GeoTIFF.
- [x] TTL-кеш поиска сцен по AOI/sensor/lookback/max_results.
- [x] Общий raster cache по provider/product/asset/AOI.
- [x] Cleanup старых кешей и output-файлов по retention.
- [x] Materializer: scene token → full-resolution raster asset.
- [x] AOI geometry в registry и crop raster по AOI.
- [x] Optional shoreline/land mask по GeoJSON.
- [x] Automatic land/shoreline mask builder из URL или локального ZIP/SHP/GeoJSON.
- [x] Land mask подготавливается при deploy один раз, если файла еще нет.
- [x] Провайдеры scene search: ASF, CDSE STAC, Planetary Computer, EarthSearch, Sentinel Hub Catalog.
- [x] Auxiliary providers: Copernicus Marine toolbox, local AIS CSV, NOAA MarineCadastre archive adapter.
- [x] Provider dependencies вынесены в extras: `scene-providers`, `aux-providers`, `providers`.
- [x] Единственные поддерживаемые shell-скрипты: `install_telegram_bot.sh` и `deploy_telegram_bot.sh`.
- [x] `deploy_telegram_bot.sh` содержит provider prompts/preflight, Telegram token prompt/getMe, command registration, land mask once-on-deploy и cleanup.
- [x] Runtime-check учитывает `MARINE_TRACK_PROVIDER_PROFILE` и не валит core-only deployment.
- [x] Overview PNG с точками судов.
- [x] Crop PNG по каждому судну.
- [x] Detection metadata сохраняется в модели, GeoJSON/report output и Telegram pipeline.
- [x] Wake association вокруг каждого судна.
- [x] Несколько сохраненных пользовательских bbox/AOI.
- [x] Пагинация списка сцен в Telegram без повторного provider search при перелистывании.
- [x] First-run hardening install/deploy: env lifecycle, Telegram getMe, provider preflight, runtime dirs, land mask preservation.
- [x] Локальный smoke-check без запуска Telegram polling.
- [ ] Progress states для долгих операций: search/materialize/detect/render/send.
- [ ] Режим “только картинки / только файлы”.
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
- [x] одноразовая сборка land mask при `deploy_telegram_bot.sh`, если mask-файла еще нет.

### Этап 3. Sentinel-2 optical path

- [x] Detection-capable STAC search для Sentinel-2 GeoTIFF/COG assets.
- [x] Sentinel Hub Catalog provider как metadata/search provider.
- [ ] B02/B03/B04/B08 asset selection как полноценный band stack.
- [ ] RGB/NIR composite.
- [ ] SCL/cloud mask.
- [ ] water mask.
- [x] bright object detector на single-band/visual GeoTIFF через local CFAR.

### Этап 4. Wake/track enrichment

- [x] Crop around vessel.
- [x] Hough wake axis association.
- [x] Heading estimation from wake axis с 180° ambiguity flag.
- [x] Local AIS CSV adapter.
- [x] NOAA MarineCadastre daily ZIP adapter with configured base URL.
- [ ] AIS track line rendering around acquisition time.
- [ ] Per-vessel crop overlay.

### Этап 5. Reporting

- [x] Telegram summary message.
- [x] Documents: GeoJSON, CSV, Parquet, report JSON.
- [x] Limit crop count by confidence if detections are many.
- [x] Detection metadata сохранена в `VesselDetection` и `to_geojson_feature()`.
- [x] `report.json` содержит raster cache status.
- [x] Telegram summary показывает `search_cache` и `raster_cache` status.

### Этап 6. Provider access audit and deployment profiles

- [x] ASF provider implemented via `asf_search`.
- [x] CDSE STAC provider supports optional OAuth bearer token.
- [x] Planetary Computer provider implemented via STAC and signed assets.
- [x] EarthSearch provider implemented for Sentinel-2 L2A only.
- [x] Sentinel Hub Catalog provider implemented via OAuth Catalog API.
- [x] Copernicus Marine provider implemented via official toolbox.
- [x] Active provider list in `config/sources.yaml` matches implemented code.
- [x] Provider dependencies split into optional extras: `scene-providers`, `aux-providers`, `providers`.
- [x] `install_telegram_bot.sh` and `deploy_telegram_bot.sh` support `--providers all|scene|aux|core|none`.
- [x] Provider key configuration and preflight integrated into `deploy_telegram_bot.sh`.
- [x] Runtime-check imports provider modules according to `MARINE_TRACK_PROVIDER_PROFILE`.
- [x] Provider access documentation added to `docs/PROVIDERS.md` and README.

### Этап 7. Cache lifecycle and API minimization

- [x] `cache_policy.py`: единая политика cache dirs, TTL, retention, cleanup.
- [x] `detection_scene_search.py`: TTL-кеш provider scene search.
- [x] `scene_materializer.py`: общий raster cache по product/asset/AOI.
- [x] Land mask once-on-deploy and cleanup integrated into `deploy_telegram_bot.sh`.
- [x] `marine-track cleanup-cache`: ручная очистка кешей и outputs.
- [x] Расширить кеширование на обычные `/dates` и `/bboxdates`, а не только `/detectbbox`.
- [ ] Добавить lock-файлы для конкурентного скачивания одного asset несколькими процессами.

### Этап 8. Telegram UX

- [x] Сохранять несколько bbox/AOI per-user вместо одного `last_bbox`.
- [x] Dedup одинаковых bbox и лимит количества сохраненных районов.
- [x] `/areas` и `📍 Мои районы` с действиями `🔎 Детекция`, `🕒 Сроки`, `🗑 Удалить`.
- [x] Пагинация `/dates` и `/bboxdates` по сохраненному `scenes_json`.
- [x] Короткие callback_data для районов и страниц.
- [ ] Progress states для long-running pipeline: search/materialize/detect/render/send.
- [ ] Режим выдачи “только картинки / только файлы”.
- [ ] AIS track rendering.

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
- 2026-07-06: добавлен `land_mask_update.py` и CLI-команда `marine-track update-land-mask`; поддержаны URL, локальный ZIP/SHP/GeoJSON, cache, force rebuild и AOI clipping; `.env.example`, README, runtime-check и тесты обновлены.
- 2026-07-06: реализован cache lifecycle: TTL-кеш scene search для `/detectbbox`, общий raster cache, once-on-deploy land mask, retention cleanup, CLI `cleanup-cache`, Telegram/report cache status.
- 2026-07-06: установка и деплой консолидированы в два shell-скрипта: `install_telegram_bot.sh` и `deploy_telegram_bot.sh`; helper/wrapper scripts выведены из эксплуатации, а их логика встроена в deploy.
- 2026-07-06: проведен аудит оставшихся пунктов плана; общий `run_search_stage` переведен на TTL-кеш для `/dates` и `/bboxdates`; wake-модуль подключен к detection pipeline через Canny+Hough association вокруг каждого судна, heading пишется с 180° ambiguity и рисуется на crop.
- 2026-07-07: реализованы несколько сохраненных bbox/AOI per-user, `/areas`, `📍 Мои районы` с действиями детекции/сроков/удаления и пагинация списка сцен через локальные registry/scenes_json без нового provider search.
- 2026-07-07: усилен первый запуск на сервере: deploy сохраняет generated land mask между релизами, создает writable runtime dirs, token/getMe и command registration остаются до restart, добавлен `python -m marine_track.smoke_check` и troubleshooting.
