# Каталог признаков и физических параметров Marine Track

Статус: целевой контракт для MVP-0.2 и последующей научной валидации. Большая часть полей ниже ещё не реализована. Каталог отделяет измеряемые признаки от решений и не объявляет эвристический score вероятностью судна.

## 1. Принципы

1. Сначала проверяется применимость метода и качество сцены, затем вычисляются evidence-признаки.
2. Сырые измерения, производные признаки, внешний reference и итоговое решение хранятся раздельно.
3. Каждый числовой признак имеет units/domain, способ вычисления, missing reason и версию алгоритма.
4. Sentinel-1 amplitude, power/backscatter и dB нельзя смешивать в одной формуле без явного преобразования.
5. Фиксированный универсальный порог не задаётся до pilot benchmark; пороги выбираются только на validation split.
6. Отсутствующий или неприменимый признак остаётся `null`, а не превращается в ноль.

Целевая последовательность:

```text
processable asset
  → calibration/units + valid-water mask
  → scene applicability gates
  → object features
  → optional wake features
  → optional AIS/ocean reference
  → separate evidence/quality/uncertainty
  → calibrated decision after benchmark
```

## 2. Признаки объекта

| Поле | Определение | Domain/units | Зачем нужно | QC |
|---|---|---|---|---|
| `object.robust_cnr` | `(CUT - median(training)) / (1.4826 * MAD(training) + eps)` | безразмерный, в зафиксированном radiometric domain | Устойчивый contrast-to-clutter без загрязнения guard cells | `training_valid_fraction`, `zero_mad` |
| `object.peak_to_clutter_db` | Разность peak и локального clutter в dB | dB, только для calibrated power/backscatter | Интерпретируемая сила яркой цели | `units_known`, `not_saturated` |
| `object.persistence` | Доля допустимых комбинаций window/guard/threshold, при которых объект стабильно обнаружен и сопоставлен | `[0, 1]` | Устойчивость к выбору параметров вместо одного магического порога | `parameter_grid_id`, `match_tolerance_m` |
| `object.area_m2` | Площадь connected component по transform/CRS | м² | Фильтр физического размера, независимый от GSD | `scale_valid`, `edge_truncated` |
| `object.length_m`, `object.width_m` | Оси fitted shape в физическом масштабе | м | Геометрия цели и resolvedness | `psf_unknown`, `pixel_anisotropy` |
| `object.compactness` | Нормированное отношение площади к периметру | безразмерный | Отделение компактного объекта от протяжённого clutter | `perimeter_method` |
| `object.solidity` | Площадь объекта / площадь convex hull | `[0, 1]` | Выявление фрагментации и нерегулярного clutter | `min_pixels` |
| `object.rectangularity` | Площадь объекта / площадь oriented bounding box | `[0, 1]` | Hull-like geometry, если объект разрешён | `resolvedness` |
| `object.resolvedness` | Length/width относительно GSD и оценённой PSF | безразмерный | Gate для shape и hull heading | `gsd_known`, `psf_source` |
| `object.distance_to_land_m` | Минимальная геодезическая/проекционная дистанция до versioned coastline | м | Nearshore false-alarm stratification | `coastline_dataset`, `coastline_resolution` |
| `object.distance_to_edge_m` | Дистанция до AOI/raster/valid-data edge | м | Отбраковка обрезанных и border-кандидатов | `edge_type` |
| `object.valid_water_fraction` | Доля валидной воды в локальном окружении | `[0, 1]` | Gate перед detector/wake | `water_mask_version` |

`CUT` — cell under test. `training` — обучающее кольцо без CUT и guard cells. При нулевом `MAD` contrast не должен автоматически становиться уверенным положительным результатом: нужен отдельный `zero_mad` flag и документированный fallback.

### Dual-polarization

При наличии согласованных co-pol/cross-pol bands добавляются:

```text
dual_pol.delta_db = sigma0_co_db - sigma0_cross_db
dual_pol.ratio_linear = sigma0_co_linear / (sigma0_cross_linear + eps)
dual_pol.local_contrast_co_db
dual_pol.local_contrast_cross_db
dual_pol.coherence_of_support
```

Band alignment, calibration, incidence angle и nodata mask должны быть одинаково определены. Ratio из dB-значений и difference из линейных amplitude без преобразования запрещены.

## 3. Признаки следа

Wake-признаки вычисляются только в water-only crop после подавления суши, nodata и границ. Одна сильная Hough-линия не считается следом.

| Поле | Определение | Интерпретация/QC |
|---|---|---|
| `wake.line_strength_norm` | Line/Radon accumulator, нормированный на длину валидного участка и локальную edge density | Снижает преимущество длинных border/coast lines |
| `wake.continuity` | Доля поддержанных отсчётов вдоль hypothesis; отдельно `max_gap_fraction` | Проверяет физически связный след, а не набор случайных edges |
| `wake.origin_residual` | Дистанция candidate centroid до оси/вершины, нормированная на GSD и, если разрешено, длину корпуса | Проверяет, что линия действительно начинается у кандидата |
| `wake.aft_sector_ratio` | Evidence в выбранном кормовом секторе / evidence в противоположном секторе | Помогает разрешать направление; без устойчивого преимущества остаётся 180° ambiguity |
| `wake.hull_alignment_residual_deg` | Минимальная circular difference оси корпуса и следа modulo 180° | Применимо только при resolved hull orientation |
| `wake.arm_angle_residual_deg` | Отклонение пары arms от выбранной Kelvin-геометрии | Только если обе arms разрешены и vertex локализован |
| `wake.bilateral_symmetry` | Симметрия геометрии/энергии левой и правой arms; imbalance хранится отдельно | Сильная асимметрия не всегда ложна, поэтому это feature/QC, а не жёсткое правило |
| `wake.width_growth_slope` | Рост ширины следа по расстоянию от кандидата | Отличает расширяющийся след от прямой границы |
| `wake.texture_anisotropy` | Structure-tensor/Radon anisotropy относительно оси | Поддержка направленной текстуры |
| `wake.spectral_coherence` | Устойчивость spectral/autocorrelation peak на нескольких cross-axis профилях вдоль следа | Заменяет вывод по одному профилю |
| `wake.positive_negative_balance` | Evidence bright/dark components в согласованном radiometric domain | SAR/optical wake может содержать оба знака контраста |

Для углов используется circular distance:

```text
d180(a, b) = abs(((a - b + 90) mod 180) - 90)
```

До калибровки сохраняются все component features и причины rejection. `wake_score` допускается только как versioned ranking score; `wake_probability` — после held-out calibration.

## 4. Условия наблюдения и применимость

| Поле | Источник | Роль |
|---|---|---|
| `scene.incidence_angle_deg` | STAC/product metadata | Стратификация контраста и detector thresholds |
| `scene.polarizations` | STAC/product metadata | Выбор sensor-specific feature set |
| `scene.gsd_x_m`, `scene.gsd_y_m` | raster transform/CRS | Физический масштаб и минимально разрешимый объект/след |
| `scene.valid_water_fraction` | water/land/nodata mask | Scene/crop quality gate |
| `environment.wind_speed_mps`, `wind_direction_deg` | Versioned ocean/meteo dataset | Sea clutter и наблюдаемость следа |
| `environment.wave_height_m`, `wave_period_s`, `wave_direction_deg` | Copernicus Marine или зафиксированный fallback | Natural wave clutter и applicability wake spectrum |
| `environment.current_east_mps`, `current_north_mps` | Copernicus Marine | Разделение speed over ground и speed through water |
| `environment.depth_m` | GEBCO/versioned bathymetry | Проверка deep/finite-depth regime |
| `optical.cloud_fraction`, `glint_flag`, `illumination` | SCL/metadata/derived | Applicability optical detector |

Для wave-speed inference должна использоваться конечноглубинная dispersion relation, а deep-water approximation разрешается только после проверки применимости:

```text
omega^2 = g * k * tanh(k * h)
```

где `k` — wave number, `h` — глубина. Порог по `k*h` не фиксируется до исследования чувствительности на benchmark. При наличии течения отдельно хранятся наблюдаемый ground-relative вектор, current vector и оценка water-relative компоненты; скалярное вычитание скоростей без направлений недопустимо.

## 5. AIS и reference-признаки

AIS — внешний, неполный и потенциально ошибочный reference, а не автоматическая ground truth.

Обязательные поля сопоставления:

```text
reference.ais.status
reference.ais.mmsi
reference.ais.sog_knots
reference.ais.cog_deg
reference.ais.distance_m
reference.ais.time_offset_s
reference.ais.interpolation_gap_s
reference.ais.point_count
reference.ais.assignment_margin_m
reference.ais.source
reference.ais.license_or_access
```

Требования к match:

1. Учитывать acquisition start/end и неопределённость времени, а не только один timestamp сцены.
2. Ограничивать максимальный interpolation gap.
3. Выполнять one-to-one assignment между candidates и AIS targets; один MMSI не должен независимо подтверждать несколько кандидатов.
4. Хранить `matched`, `unmatched`, `ambiguous`, `stale`, `out_of_window`.
5. Обрабатывать longitude interpolation около antimeridian.
6. Не переписывать собственные `heading_*`/`speed_*`: AIS остаётся в `reference.ais.*`.

## 6. Целевая схема результата

```json
{
  "candidate_status": "candidate",
  "ship_evidence": {
    "ranking_score": 0.68,
    "model_version": "classical-s1-v2"
  },
  "wake_evidence": {
    "ranking_score": null,
    "applicable": false,
    "reasons": ["insufficient_valid_length"]
  },
  "scene_quality": {
    "score": 0.71,
    "flags": ["single_pol", "near_scene_edge"]
  },
  "heading": {
    "axis_deg": null,
    "direction_deg": null,
    "ambiguity_deg": 180,
    "uncertainty_deg": null
  },
  "speed": {
    "value_knots": null,
    "method": "not_estimated",
    "uncertainty_knots": null
  },
  "research_proxies": {
    "kelvin_speed_proxy_knots": null
  },
  "reference": {
    "ais": null
  }
}
```

Запрещённые до benchmark подмены:

- `confidence` как вероятность судна;
- `speed_knots` из Kelvin proxy;
- AIS SOG в поле собственной спутниковой оценки;
- `heading_deg` как направление, если получена только ось modulo 180°;
- ноль вместо `null` для неприменимого или отсутствующего параметра.

## 7. Порядок реализации

### Этап A — воспроизводимый baseline

- calibration/units/asset contract;
- valid-water mask и физический масштаб;
- guard-cell robust CNR;
- physical shape, edge/coast distance и parameter persistence;
- separate result schema и provenance.

### Этап B — wake research

- water-only hypotheses, continuity/origin/sector features;
- arm/vertex/angle tests;
- multi-profile spectral coherence;
- depth/current/wave applicability и uncertainty.

### Этап C — калибровка

- fixed scene/orbit/AOI/time split и negative strata;
- one-to-one AIS/reference assignment;
- bootstrap confidence intervals;
- отдельно calibrated ship/wake decisions;
- speed metrics только на applicable paired subset.

Связанные документы: [`TECHNICAL_SPEC.md`](TECHNICAL_SPEC.md), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md), [`DETECTION_METHOD.md`](DETECTION_METHOD.md), [`SCIENCE_BASIS.md`](SCIENCE_BASIS.md).
