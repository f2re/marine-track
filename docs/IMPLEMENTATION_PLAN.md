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
- [x] Overview PNG с точками судов.
- [x] Crop PNG по каждому судну.
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
- [ ] автоматическое скачивание/обновление coastline/land mask.

### Этап 3. Sentinel-2 optical path

- [x] Detection-capable STAC search для Sentinel-2 GeoTIFF/COG assets.
- [ ] B02/B03/B04/B08 asset selection как полноценный band stack.
- [ ] RGB/NIR composite.
- [ ] SCL/cloud mask.
- [ ] water mask.
- [x] bright object detector на single-band/visual GeoTIFF через local CFAR.

### Этап 4. Wake/track enrichment

- [ ] Crop around vessel.
- [ ] Hough/Radon wake axis association.
- [ ] Heading estimation from wake axis.
- [ ] AIS CSV track line around acquisition time.
- [ ] Per-vessel crop overlay.

### Этап 5. Reporting

- [x] Telegram summary message.
- [x] Documents: GeoJSON, CSV, Parquet, report JSON.
- [x] Limit crop count by confidence if detections are many.

## Журнал прогресса

- 2026-07-06: создан план реализации; старт этапа 1.
- 2026-07-06: реализованы `scene_materializer.py`, `detection_pipeline.py`, `rendering/overview.py`, `rendering/vessel_crop.py`; следующий шаг — подключение Telegram `/detect` и тесты.
- 2026-07-06: подключены Telegram `/detect <token>` и callback `mtdetect:<token>`; кнопка `🔎 Детекция` добавлена к срокам; добавлены тесты сквозного detection pipeline на synthetic GeoTIFF.
- 2026-07-06: AOI GeoJSON сохраняется в registry, materializer делает crop raster по AOI с reprojection; добавлен detection-capable STAC search и команда `/detectbbox`.
- 2026-07-06: detector переключен на local-CFAR style режим с `local_window_px`/`guard_window_px`; параметры detector-а пишутся в metadata детекций и `report.json`; README и Telegram-инструкции актуализированы.
- 2026-07-06: добавлен optional land/shoreline mask по GeoJSON в EPSG:4326; маска перепроецируется в CRS растра, буферизуется и применяется до normalizing/CFAR; настройки добавлены в `.env.example`, runtime-check и документацию.
