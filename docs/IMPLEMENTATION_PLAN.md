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
- [ ] `/detect <token>`.
- [ ] Materializer: scene token → full-resolution raster asset.
- [ ] Overview PNG с точками судов.
- [ ] Crop PNG по каждому судну.
- [ ] Wake association вокруг каждого судна.
- [ ] AIS track rendering.

## Реализация по этапам

### Этап 1. Detection skeleton по token

- [ ] `scene_materializer.py`: выбор GeoTIFF/COG asset из scene registry.
- [ ] `detection_pipeline.py`: token → raster → detections → output files.
- [ ] `rendering/overview.py`: общий PNG с точками судов.
- [ ] `rendering/vessel_crop.py`: crop PNG по каждому судну.
- [ ] Telegram `/detect <token>` и callback `mtdetect:<token>`.
- [ ] Тесты materializer/pipeline/rendering.

Ограничение этапа: обрабатываются только raster assets, которые можно открыть как GeoTIFF/COG. ASF ZIP/GRD не обрабатывается как GeoTIFF и должен давать понятную ошибку.

### Этап 2. Sentinel-1 RTC path

- [ ] Предпочитать Planetary Computer `sentinel-1-rtc` для детекции.
- [ ] VV/VH asset selection.
- [ ] AOI crop.
- [ ] shoreline/land mask.
- [ ] local CFAR.

### Этап 3. Sentinel-2 optical path

- [ ] B02/B03/B04/B08 asset selection.
- [ ] RGB/NIR composite.
- [ ] SCL/cloud mask.
- [ ] water mask.
- [ ] bright object detector.

### Этап 4. Wake/track enrichment

- [ ] Crop around vessel.
- [ ] Hough/Radon wake axis association.
- [ ] Heading estimation from wake axis.
- [ ] AIS CSV track line around acquisition time.
- [ ] Per-vessel crop overlay.

### Этап 5. Reporting

- [ ] Telegram summary message.
- [ ] Documents: GeoJSON, CSV, Parquet, report JSON.
- [ ] Limit crop count by confidence if detections are many.

## Журнал прогресса

- 2026-07-06: создан план реализации; старт этапа 1.
