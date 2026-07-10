# Методика текущей детекции Marine Track

## 1. Что анализируется сейчас

Текущий pipeline анализирует **один** выбранный full-resolution GeoTIFF/COG asset. Несколько спутниковых снимков не накладываются, temporal stack не строится, Sentinel-2 multi-band composite не выполняется.

Фактическая цепочка:

```text
scene token → GeoTIFF/COG → optional AOI crop → land mask → percentile normalize → local-CFAR-style threshold → connected components → geometry/scale metrics → Hough/AIS enrichment → outputs
```

Результат текущего object stage — `vessel_candidate`, а не подтверждённое судно.

## 2. Object detector

1. Читается первый raster band.
2. nodata и optional land/shoreline mask переводятся в NaN.
3. Значения нормализуются percentiles 2/98 в пределах raster.
4. В local window оцениваются mean/std.
5. Кандидатный пиксел превышает `mean + threshold_sigma * std`.
6. Connected components фильтруются по `min_area_px/max_area_px`.
7. Сохраняются centroid, bbox, area, peak/mean score, background mean/std, contrast, axis/elongation.
8. По affine transform/CRS оцениваются pixel scale и физическая площадь.

### Важное ограничение

Это **local-CFAR-style heuristic**, а не полноценный guard-cell CFAR: текущий background window включает candidate, а `guard_window_px` используется как local maximum filter. Поэтому threshold и `contrast_sigma` не имеют гарантированной false-alarm semantics.

Кроме того:

- maximum-filter после threshold может фрагментировать протяжённые яркие объекты, поэтому shape/area становятся зависимы от окна;
- percentile 2/98 normalization клипирует верхний хвост, часто насыщает `peak_score=1` и делает половину текущего confidence слабо различающей кандидаты;
- elongation получает положительный вклад в score и может повышать ranking береговых линий/волнового clutter;
- min/max area задаются в pixels, поэтому физический фильтр меняется вместе с GSD;
- detector рассчитан на bright compact targets;
- темные суда, dark wake, sea clutter, port/coastal clutter и wind-dependent contrast требуют отдельных режимов;
- единицы входного raster (DN/amplitude/sigma0/gamma0/dB) сейчас не входят в обязательный processing contract;
- thresholds из `config/processing.yaml` фактически не управляют всеми CLI/Telegram paths: часть параметров hard-coded;
- raster читается целиком, а не tiles, что создаёт RAM/latency risk для больших AOI.

При AOI crop нужен отдельный valid-data mask: если source nodata не задан, filled pixels вне AOI не должны интерпретироваться как валидный нулевой фон.

## 3. Масштаб

Пиксельный масштаб вычисляется локально:

```text
pixel center → lon/lat
right/down neighbor → lon/lat
haversine → x_m/y_m
```

Это лучше, чем фиксированное «10 м», но является локальным приближением. Для rotated/anisotropic grids, reprojected crops и объектов с большим размером нужно хранить `x_m`, `y_m`, area и uncertainty. Использование одного `mean_m` для length/width/wavelength может давать bias при заметной анизотропии.

## 4. Wake association

В crop вокруг candidate выполняются Canny + Hough. Берётся line hypothesis, проходящая рядом с centroid. Heading строится по географическому направлению оси, а ambiguity выставляется `180°`.

Это не доказательство wake. Текущая реализация:

- читает исходный crop без той же shoreline mask;
- не удаляет image borders/береговые линии;
- не проверяет кормовой сектор, arm pair, vertex, continuity и Kelvin angle;
- не различает central turbulent wake и Kelvin arms;
- не имеет calibrated `wake_score`.

Следующий вариант должен выполнять line search только в valid-water mask и возвращать набор quality flags. При непрохождении QC heading следует оставлять `not_estimated`.

## 5. Confidence/evidence

Текущая confidence — ranking score:

```text
0.50 * peak_score
+ 0.35 * clamp(contrast_sigma / 8)
+ 0.15 * clamp((elongation - 1) / 5)
```

Это не вероятность судна, потому что отсутствуют labels, calibration split, negative scenes и uncertainty. До benchmark использовать названия `evidence_score`/`ranking_score`.

Значение score не сопоставимо между AOI, providers и radiometric products до sensor-specific calibration. Сначала нужны отдельные `ship_evidence`, `wake_evidence`, `scene_quality`, `applicability` и `uncertainty`; объединённая вероятность допустима только после held-out calibration.

Целевая схема:

```text
ship_score + wake_score + quality_score + uncertainty + quality_flags
```

## 6. Скорость

### AIS reference

При local AIS match pipeline записывает внешний SOG/COG reference. Нужно сохранять MMSI, distance, time gap, interpolation interval, number of points, assignment margin и ambiguity. Matching должен быть one-to-one и ограничивать interpolation gap; сейчас один MMSI может независимо сопоставиться нескольким candidates. AIS не является незаметной заменой собственному measurement.

Текущий runtime может записывать AIS SOG и Kelvin proxy в общее `speed_knots`, а overview/crops подписывать как «суда», `conf` и `speed`. Это необходимо исправить до научной оптимизации: operational speed остаётся `null`, proxy и AIS reference хранятся раздельно.

### Wake wavelength

Текущий experimental path:

1. Hough line выбирается вокруг candidate;
2. строится один profile перпендикулярно оси в crop;
3. ищутся повторяющиеся bright peaks;
4. median peak spacing переводится в метры;
5. применяется `V=sqrt(g*L/(2*pi))`.

Результат должен называться `speed_proxy`, потому что profile не доказывает, что измерена `Lmax` transverse Kelvin wave. Для научного метода требуются along-arm sampling, spectral/autocorrelation stability, depth/current/wave context, sensor geometry и uncertainty.

До валидации:

```text
speed_method = not_estimated                 # operational default
speed_proxy_method = kelvin_wavelength_exp  # research field
```

## 7. Что накладывается

Сейчас накладываются только auxiliary layers:

- land/shoreline mask — suppression;
- AIS track — post-detection reference/overlay;
- Hough wake axis — feature того же raster.

Другие спутниковые снимки, S1/S2 composites и temporal differences не анализируются.

## 8. Следующий научный detector

1. S1 calibration/unit contract и valid-water mask.
2. Guard-cell CFAR с robust clutter statistics.
3. dual-pol/incidence/orbit/context features.
4. tile inference и overlap deduplication.
5. object evidence + land/edge/port rejection.
6. wake line continuity/sector/arm/angle/vertex tests.
7. AIS quality and physical validation.
8. benchmark with labels and negative scenes.

Научные приёмочные метрики: precision/recall/F1, POD/FAR/CSI, false alarms/km², localization error; для wake — false-wake rate and angular error; для speed — bias/MAE/RMSE/coverage against paired reference.

Определения производных признаков, units и QC: [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md).
