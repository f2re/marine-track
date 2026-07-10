# Научное основание Marine Track

## 1. Научная постановка

Спутниковая сцена не наблюдает «судно» напрямую как идеальный объект: наблюдаемый сигнал зависит от корпуса, волнения, ветра, угла визирования, поляризации, глубины, течения, обработки продукта и времени съёмки. Поэтому система должна разделять:

```text
object evidence → wake evidence → scene quality → validation/reference
```

Это исключает подмену эвристического score вероятностью и не позволяет выдавать скорость при отсутствии физически применимого признака.

## 2. Sentinel-1 SAR

Sentinel-1 C-band SAR работает днём/ночью и сквозь облачность, поэтому является основным каналом для ship-candidate detection. При этом SAR intensity зависит от sea clutter и условий наблюдения; яркий пик не равен судну автоматически. Входной продукт должен иметь известные units/calibration, polarization, incidence angle, orbit/mode и valid mask.

Базовый научный pipeline:

1. calibration/unit normalization;
2. water/land/shoreline and nodata mask;
3. robust clutter estimate;
4. guard-cell CFAR или эквивалентная модель с измеряемым false-alarm rate;
5. object geometry and dual-pol/context features;
6. rejection of coastline, ports, borders and invalid areas;
7. independent validation on labels/AIS.

CFAR в текущем коде является лишь local-CFAR-style эвристикой: фон включает target, а `guard_window_px` не реализует guard cells. Это должно быть исправлено до научной оценки.

## 3. Почему wake — отдельный признак

Кильватер состоит из разных физических компонентов: near-field turbulent/foam wake, transverse waves и divergent Kelvin arms. В SAR они могут быть яркими или тёмными и проявляться несимметрично. Поэтому один Hough line около centroid — только гипотеза.

Для подтверждения wake нужны:

- линия/полоса на достаточной длине;
- continuity и устойчивость к scale/threshold;
- связь с кандидатом в кормовом секторе;
- contrast относительно локального sea clutter;
- при наличии Kelvin arms — vertex/angle/arm symmetry;
- suppression береговых и image-edge line features.

Radon/Hough и sparse-методы являются обоснованными направлениями для линейной структуры wake, но их результат требуется проверять относительно геометрии и условий сцены. [ESA описывает Radon-based SAR wake detection](https://earth.esa.int/eogateway/success-story/sar-synergy-data-for-maritime-surveillance/ship-wake-detection-using-sar), а обзор 2024 года систематизирует классические и deep-learning методы: [Mazzeo et al., 2024](https://www.mdpi.com/2072-4292/16/20/3775).

## 4. Курс

Ось wake может определить линию движения, но не всегда направление вдоль линии. Поэтому:

- axis heading хранится с `180° ambiguity`;
- направление «нос-корма» допускается только при подтверждённом vertex/asymmetry, hull orientation или внешнем reference;
- heading error следует считать circular error, а не обычной разностью без обработки 0/360.

## 5. Скорость по Kelvin wake

Для глубокой воды дисперсионная связь даёт приближение:

```text
V = sqrt(g * Lmax / (2*pi))
```

где `Lmax` — измеренная длина волны, а `V` — скорость относительно воды в идеализированной постановке. На практике применимость ограничивают:

- конечная глубина и bathymetry;
- течение — разница speed through water/over ground;
- wind-generated waves и sea-state;
- угол визирования и азимутальная ориентация;
- пространственное разрешение и число наблюдаемых периодов;
- асимметрия/частичное исчезновение arm;
- нелинейность, Froude regime и форма судна.

Научные работы по wake speed используют спектральную/геометрическую структуру wake, а не произвольное расстояние между пиками одного поперечного профиля. См. [The speed and beam of a ship from its wake's SAR images](https://cris.tau.ac.il/en/publications/the-speed-and-beam-of-a-ship-from-its-wakes-sar-images) и обзор конечной глубины/волнения [Shugan et al., 2022](https://www.mdpi.com/2072-4292/14/7/926).

Поэтому текущая реализация `cross_axis_profile_peaks` должна интерпретироваться как `speed_proxy`, иметь uncertainty/quality flags и не использоваться для основного оперативного вывода.

## 6. Sentinel-2

Sentinel-2 MSI может быть полезен для оптического корпуса, пены, альбедо и Kelvin waves при дневной ясной сцене. Но bands снимаются push-broom детекторами с межканальными временными сдвигами; скорость через inter-band displacement требует реальных band delays, регистрации и геометрической модели. [Binet et al.](https://isprs-annals.copernicus.org/articles/V-1-2022/57/2022/) показывают, что знание задержек является существенным для динамических объектов.

До появления B02/B03/B04/B08 stack, SCL/cloud/shadow/water/glint mask и optical-specific QC текущий single-band путь нельзя считать полноценной Sentinel-2 методикой.

## 7. Валидация

AIS полезен, но не является безусловной истиной: возможны пропуски, latency, неверный MMSI, spatial mismatch и gaps. Для каждого match нужно хранить:

- временной gap и интервал интерполяции;
- расстояние detection–AIS;
- число точек track;
- ambiguity среди нескольких MMSI;
- difference in heading/speed;
- timestamp и provenance источника AIS.

Независимая оценка должна включать manual labels и negative scenes. Соседние кадры одного прохода нельзя распределять между train и test. Результаты стратифицируются по sensor/polarization/incidence/wind/depth/coast/open sea/day-night.

## 8. Метрики

### Detection

Precision, recall, F1, POD, FAR, CSI, false alarms/km², median/p95 localization error.

### Wake

Wake detection rate, false-wake rate, axis angular MAE/p95, arm/continuity residuals.

### Speed

Bias, MAE, RMSE, median absolute error, coverage and uncertainty calibration against AIS/independent reference. Для каждой метрики указывается число применимых paired cases; отсутствие wake не превращается в нулевую скорость.

### Operational

Provider success rate, latency, bytes downloaded, cache hit rate, failure class distribution and reproducibility hash.

Приёмка новой методики — сравнение с classical baseline на независимой выборке и confidence intervals, а не один удачный quicklook.

## 9. Литература и данные

- [Copernicus Sentinel-1 mission and products](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-1).
- [CDSE STAC API](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) и [CDSE OData](https://documentation.dataspace.copernicus.eu/APIs/OData.html).
- Karakuş, Rizaev, Achim, [Ship Wake Detection in SAR Images via Sparse Regularization](https://doi.org/10.1109/TGRS.2019.2947360).
- [A Systematic Review of Ship Wake Detection Methods in SAR Images](https://www.mdpi.com/2072-4292/16/20/3775).
- [Planetary Computer Sentinel-1 RTC dataset](https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc).
- [Copernicus Marine products](https://data.marine.copernicus.eu/products).
