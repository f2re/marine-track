# Калибровка phase 2

## Назначение

Phase 2 расширяет candidate-level калибровку независимой разметкой участков спутниковой сцены. Это необходимо, чтобы учитывать не только уже найденные detector candidates, но и:

- пропущенные суда;
- ложные срабатывания на морском волнении, берегу, портах и сооружениях;
- различия между sensor, processing level, polarization/band и GSD;
- качество следа и неоднозначность направления.

Phase 2 не превращает `ranking_score` в вероятность и не изменяет CFAR автоматически.

## Telegram-сценарий

Администратор открывает:

```text
/calibrate → 🌊 Независимые tiles · phase 2
```

Доступны действия:

1. `Сформировать tiles` — построить воспроизводимые участки сцен независимо от текущих срабатываний.
2. `Размечать` — выбрать клетку 3×3 с центром корпуса.
3. Указать `Судна нет`, `Несколько`, `Не уверен` или `Пропустить`.
4. Для подтверждённой цели отдельно разметить след:
   - нет следа;
   - turbulent wake;
   - Kelvin arms;
   - оба типа;
   - не уверен.
5. Для следа указать сектор направления. Поле `ambiguity_180=true` сохраняется явно.
6. Выполнить held-out evaluation.
7. Предложить, активировать или откатить профиль.

AIS показывается только как reference metadata и не считается безусловной ground truth.

## Генерация tiles

Источником являются сохранённые `detections/*/report.json` и соответствующие GeoTIFF/COG. Окна формируются по регулярной сетке с 50% overlap и детерминированным порядком. Они не центрируются на detection candidates.

Поддерживаются страты:

- `open_sea`;
- `coastline`;
- `port`;
- `offshore_structure`;
- `high_clutter`.

Без дополнительного контекстного GeoJSON автоматически различаются open sea, coastline и high clutter. Для портов и морских сооружений рекомендуется задать `MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON` с полигонами и `properties.stratum`.

Каждое задание хранит:

- source product/raster/report;
- window row/col/size;
- valid-data fraction;
- stratum и scene regime;
- текущие detector candidates внутри окна;
- AIS reference status;
- tile area;
- applicability contract;
- deterministic split и scene group.

## Защита от leakage

Split назначается хешированием `scene_group_id`, который включает sensor, orbit/pass, час наблюдения и AOI/raster key. Один scene/pass group не может попасть одновременно в train, calibration и test.

Распределение:

```text
train        65%
calibration  17%
test         18%
```

## Applicability

Профиль разделяется по следующим признакам:

- sensor;
- collection;
- processing level;
- polarization;
- band;
- units;
- GSD bucket;
- detector type;
- processing config hash;
- scene regime.

Если необходимые metadata отсутствуют, сохраняется значение `unknown`; оно не подменяется предположением.

## Метрики

CLI и Telegram считают отдельно для train/calibration/test:

- precision;
- recall/POD;
- F1;
- FAR;
- CSI;
- false alarms per km²;
- missed-target count;
- localization MAE и p95.

Для test split строятся group-bootstrap 95% confidence intervals. Bootstrap выполняется по scene groups, а не по отдельным tiles.

## Promotion gate

Профиль активируется только явно и только когда:

- достаточно calibration groups;
- достаточно test groups;
- test F1 улучшает активный baseline минимум на установленную величину;
- test recall не ухудшается.

Автоматически применяется только `ranking_score` post-filter. Параметры CFAR сохраняются как `null/not applied`.

Предыдущий активный профиль переносится в history и может быть восстановлен через Telegram или CLI.

## CLI

```bash
marine-track calibration-generate-tiles \
  --output-dir runs/telegram \
  --context-geojson data/calibration_context.geojson

marine-track calibration-evaluate --output-dir runs/telegram
marine-track calibration-propose --output-dir runs/telegram
marine-track calibration-promote --output-dir runs/telegram
marine-track calibration-rollback --output-dir runs/telegram
```

## Environment

```dotenv
MARINE_TRACK_CALIBRATION_PHASE2_MAX_TILES_PER_SCENE=24
MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALID_FRACTION=0.85
MARINE_TRACK_CALIBRATION_PHASE2_MIN_TEST_GROUPS=3
MARINE_TRACK_CALIBRATION_PHASE2_MIN_VALIDATION_GROUPS=3
MARINE_TRACK_CALIBRATION_PHASE2_MIN_IMPROVEMENT=0.01
MARINE_TRACK_CALIBRATION_PHASE2_BOOTSTRAP_SAMPLES=300
MARINE_TRACK_CALIBRATION_CONTEXT_GEOJSON=
```

## Ограничения

- Независимость tile от candidate не означает, что текущий набор сцен репрезентативен для всех морей и сезонов.
- Автоматическая water classification пока использует valid-data/clutter proxy; полноценная water/land/port mask должна развиваться отдельно.
- Wake labels не используются для изменения Kelvin speed proxy.
- Для operational probability calibration требуется отдельный probability model на held-out данных.
