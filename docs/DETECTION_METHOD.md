# Методика детекции Marine Track

## Что анализируется сейчас

Текущий detector работает по одному full-resolution GeoTIFF/COG raster asset, выбранному из STAC scene registry. В MVP не выполняется многоснимочное наложение и не строится multi-band composite.

Основная цепочка:

```text
scene token → GeoTIFF/COG asset → AOI crop → land/shoreline mask → percentile normalize → local CFAR → connected components → geospatial scale/shape metrics → wake/AIS enrichment → overview/crop/report
```

## Какие снимки накладываются

В текущем режиме детекции не накладываются несколько спутниковых снимков друг на друга. Анализируется один растровый asset сцены:

- Sentinel-1 RTC/COG или другой GeoTIFF/COG asset, если provider возвращает его в STAC assets;
- Sentinel-2 visual/single-band asset, если он выбран как detection-capable GeoTIFF/COG.

Land/shoreline mask и AIS track не являются входными спутниковыми снимками. Они накладываются как auxiliary layers:

- land/shoreline mask исключает пиксели суши и береговой зоны до thresholding;
- AIS track используется после детекции для validation/enrichment и overlay;
- wake axis ищется в crop того же raster asset, а не в отдельном изображении.

## Алгоритм детекции

1. Чтение первого raster band из GeoTIFF/COG.
2. Применение nodata и optional land/shoreline mask: суша и береговая зона становятся NaN.
3. Percentile normalization: значения приводятся к диапазону 0..1 по устойчивым процентилям.
4. Local-CFAR thresholding:
   - для каждого пикселя оценивается локальный фон `mean` и `std` в окне `local_window_px`;
   - пиксель считается кандидатом, если `value > mean + threshold_sigma * std`;
   - `guard_window_px` может оставить только локальные максимумы.
5. Connected components: соседние bright pixels объединяются в объекты.
6. Фильтр площади: `min_area_px <= area_px <= max_area_px`.
7. Для каждого объекта рассчитываются:
   - centroid в пикселях и lon/lat;
   - bbox в пикселях;
   - area_px;
   - local background mean/std;
   - peak_score, mean_score;
   - contrast_sigma;
   - major/minor axis в пикселях;
   - elongation;
   - orientation_image_deg.
8. По affine transform и CRS рассчитывается физический масштаб пикселя около centroid:
   - pixel_scale_x_m;
   - pixel_scale_y_m;
   - pixel_area_m2;
   - area_m2;
   - major_axis_m;
   - minor_axis_m;
   - equivalent_diameter_m.

## Как рассчитывается confidence

Текущая confidence — это ranking score, а не вероятность судна. Формула:

```text
0.50 * peak_score + 0.35 * clamp(contrast_sigma / 8) + 0.15 * clamp((elongation - 1) / 5)
```

Смысл:

- `peak_score` — насколько яркая цель после percentile normalization;
- `contrast_sigma` — насколько цель выделяется над локальным морским фоном;
- `elongation` — форма, вытянутая как корпус/след, получает небольшой плюс.

## Как рассчитывается скорость

Есть два источника скорости.

1. AIS SOG, если найдено соответствие detection ↔ AIS. Это приоритетный внешний reference:
   - `speed_knots = ais_sog_knots`;
   - `speed_method = ais_sog`;
   - `speed_reference = ais:<mmsi>`.

2. Экспериментальная оценка по wake wavelength, если AIS отсутствует и вокруг цели найден wake axis:
   - в crop строится профиль яркости поперек wake axis;
   - в профиле ищутся повторяющиеся гребни/пики;
   - медианное расстояние между пиками считается wavelength_px;
   - wavelength_px переводится в wavelength_m через локальный pixel scale;
   - скорость оценивается по deep-water Kelvin approximation:

```text
V = sqrt(g * wavelength_m / (2*pi))
```

Результат записывается как:

```text
speed_method = kelvin_wavelength
speed_reference = wake_wavelength_experimental
metadata.wake.wavelength.experimental = true
```

Ограничение: это speed through water / proxy-feature, а не гарантированная speed over ground. AIS SOG, если доступен, перезаписывает экспериментальную оценку.

## Как рассчитывается масштаб

Масштаб берется не из предположений о разрешении, а из georeferencing raster-а:

```text
pixel center → lon/lat
pixel center + 1 col → lon/lat
pixel center + 1 row → lon/lat
haversine distances → x_m, y_m
```

Это работает и для projected CRS, и для EPSG:4326, потому что расчет делается через lon/lat после reprojection.

## Ограничения текущей реализации

- Нет multi-band Sentinel-2 stack B02/B03/B04/B08.
- Нет SCL/cloud/water mask для Sentinel-2.
- ASF ZIP/GRD не обрабатывается как GeoTIFF.
- Wake speed является experimental proxy и требует валидации по AIS/натурным данным.
- Detector рассчитан на bright compact targets; темные цели, сложные sea clutter и port clutter требуют отдельного режима.

## Следующие улучшения

1. Lock-файлы для raster cache, чтобы параллельные запросы не скачивали один asset одновременно.
2. Валидация wake-speed по AIS и флаги качества.
3. Sentinel-2 band stack + water/cloud mask.
4. Отдельные detector presets для SAR/open sea, nearshore и optical scenes.
