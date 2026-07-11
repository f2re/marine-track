# План реализации Marine Track

План фиксирует фактический engineering/data/science gate. Чекбокс означает подтверждённую реализацию и тест, а не намерение. Live provider access, серверный deploy и научная точность отмечаются отдельно от offline CI.

## Целевой operational contract

```text
AOI + UTC interval
→ provider search
→ typed processable raster asset
→ runtime signing/OAuth when required
→ materialization and AOI crop
→ Sentinel-1 preprocessing and valid mask
→ guard-cell CFAR candidate detector
→ optional external AIS/research wake evidence
→ GeoJSON/CSV/Parquet/report/PNG
→ Telegram
```

Выходной объект называется `vessel_candidate`. `ranking_score`/`evidence_score` не является вероятностью. Для одной сцены operational speed по умолчанию: `value_knots=null`, `method=not_estimated`. AIS SOG/COG хранится отдельно как external reference. Kelvin speed остаётся research-only proxy.

## Срез состояния на 2026-07-11

### Реализовано в `main`

- [x] Typed `SceneAsset`, capability-aware selection и authenticated/transient asset access.
- [x] Hardened scene-search cache с absolute time/capability contract и deterministic ordering.
- [x] Atomic/locked raster materialization, AOI crop, valid masks и resource limits.
- [x] Sentinel-1 preprocessing contract; Sentinel-2 single-band fail-closed/experimental.
- [x] Guard-cell CFAR, tiled inference, overlap ownership и candidate limits.
- [x] Provenance/redaction и раздельная семантика operational speed, AIS reference и research proxy.
- [x] Fail-closed Telegram authorization и user/chat-scoped scene tokens/callbacks.
- [x] Versioned immutable releases, atomic systemd switch/rollback и persistent state/cache/output.
- [x] Calibration-area and phase-2 preparation workflow.
- [x] Explicit Sentinel-1 provider canary modes `asset` и `detection`.
- [x] Compact canary AOI, transient signing/OAuth и TIFF range-read probe.
- [x] Atomic mode-0600 redacted canary reports со stage durations и typed failure.
- [x] Administrator-only Telegram `/selftest` с отдельным confirmation для detection mode.
- [x] Tokenless Planetary Computer первым для Sentinel-1 raster path.
- [x] CDSE/Sentinel Hub без полных optional credentials пропускаются до OAuth/network call.
- [x] Normal Telegram candidate detection выполняется в killable subprocess с hard wall-clock timeout.
- [x] Default detection AOI ограничен compact sector; oversized bbox отклоняется до expensive I/O.
- [x] Deploy/runtime preflight объясняет enabled/disabled provider access без вывода secrets.
- [x] Временная write-capable PR-finalization orchestration удалена после merge.

PR #29 слит в `main` как `dc3833011be8584737b047c6c322fbe8ceda5032`; cleanup PR #32 — `b128873d6e443cedc7628312babae12323fb9d62`. CI run 701: shell/ruff/189 tests/build/core runtime/no-growth mypy gate passed.

### Отдельный открытый PR #30

- [ ] Transactional Telegram user state: inter-process lock, read-modify-write transaction, temp+`fsync`+`os.replace`, mode 0600, corrupt JSON quarantine и parallel lost-update test.
- [ ] PR #30 остаётся draft и основан на более старом `main`; перед продолжением его нужно обновить после слияния PR #29, устранить временный finalize workflow и повторить полный release gate.

### Не подтверждено

- [ ] Clean install и atomic deploy на `us-vmpico` после обновления `main`.
- [ ] Post-switch Telegram healthcheck и rollback на реальном systemd service.
- [ ] Live Planetary Computer search/sign/range-read canary.
- [ ] Live detection canary с отдельным operator confirmation.
- [ ] Независимый benchmark, calibration split и uncertainty.
- [ ] Operational Sentinel-2 stack B02/B03/B04/B08 с SCL/cloud/shadow/water/glint masks.

## Матрица требований текущего gate

| Требование | Реализация | Тест/проверка | Документация | Статус |
|---|---|---|---|---|
| Processable asset, а не preview/archive | `SceneAsset`, capability selection, materializer typed errors | offline provider/materializer tests | technical spec, README | закрыто offline |
| Бесплатный path без operator token | Planetary Computer STAC + runtime signing | tokenless fallback regression | README, `.env.example` | закрыто offline; live не проверен |
| Optional OAuth не блокирует fallback | credential preflight и provider skip | complete/incomplete pair tests | README, deploy output | закрыто offline |
| Нет вечного Telegram materialize | spawned worker, GDAL HTTP limits, terminate/kill | stalled-worker timeout test | README, env template | закрыто offline |
| Bounded AOI до raster I/O | compact default sector и detection area ceiling | provider-not-called oversized AOI test | README, release gate | закрыто offline |
| Canary не запускается автоматически | explicit CLI/Telegram action, separate detection confirm | mocked canary/selftest tests | `PROVIDER_CANARY.md` | закрыто offline |
| Sanitized report/errors | centralized redaction, atomic 0600 report | secret/path/query redaction tests | provider canary doc | закрыто offline |
| Telegram mutable state transactional | PR #30 | pending parallel/recovery gate | draft state doc | открыто |
| Live provider/data access | explicit asset canary | не запускался | release gate | открыто |
| Научная точность | dataset/evaluation/calibration workflow | benchmark отсутствует | technical spec/catalog | открыто |

## P0 — завершение server engineering gate

### P0.1. Deployment нового `main`

1. Обновить server checkout fast-forward от `origin/main`.
2. Запустить `deploy_telegram_bot.sh`; зафиксировать release id/code SHA.
3. Проверить `systemctl is-active`, runtime/health output и сохранение canonical env/state/cache/output.
4. Проверить `/start`, `/status`, `/dates` и bounded `/detectbbox`.
5. Не запускать live canary автоматически. Asset canary выполнить отдельно только с явным разрешением на сетевой доступ.

### P0.2. Продолжение существующего PR #30

1. Перебазировать/обновить branch от нового `main` без создания нового PR.
2. Удалить temporary self-finalization workflow/script из итогового diff.
3. Проверить flock transaction на полном read-modify-write участке.
4. Проверить same-directory temporary, `fsync` файла и директории, `os.replace`, mode 0600.
5. Проверить corrupt active JSON quarantine и deterministic recovery.
6. Добавить multi-process lost-update test и полный mandatory gate.

### P0.3. Контролируемый typing/packaging baseline

- [x] Exact raw `mypy --no-incremental src` сохраняется в diagnostics.
- [x] CI сравнивает нормализованные error fingerprints с актуальным `main` и запрещает рост.
- [ ] Последовательно уменьшать raw debt без широких `ignore_errors`.
- [ ] Добавить Python 3.10/3.11/3.12 support matrix и clean constrained install.
- [ ] Проверить license metadata и reproducible dependency/constraints policy.

## P1 — эксплуатационная проверяемость после server gate

### P1.1. Provider canary

Asset mode:

```text
compact AOI → Sentinel-1 search → typed asset → transient signing/OAuth → TIFF range-read
```

Detection mode:

```text
separate confirmation → compact AOI → one scoped scene → materialize/preprocess/detect
```

Ограничения:

- не запускать при deploy/restart/обычном healthcheck;
- wake/Kelvin всегда выключены;
- report atomic, mode 0600 и redacted;
- отсутствие processable asset — typed failure, не «0 кандидатов»;
- live success подтверждает только integration/data access, не научную точность.

### P1.2. Operations evidence

- Сохранять latency по stages, provider success/failure class, bytes checked/downloaded и cache hit.
- Проверять expired signing/OAuth и повторный запуск.
- Проверять сохранение `.env`, state, cache и outputs при deploy/rollback.
- Не логировать credentials, signed query, local absolute paths или user content.

## P2 — научная валидация после engineering/data-access gate

1. Собрать scene manifest и data card на реальных Sentinel-1 сценах.
2. Стратифицировать open sea, coast, port, offshore/high-clutter.
3. Разметить positive/negative/uncertain, object body и optional wake geometry.
4. Зафиксировать scene-level train/validation/test split без утечки соседних сцен.
5. Добавить evaluation CLI и метрики:
   - precision, recall, F1, POD, FAR, CSI;
   - false alarms/km² и localization error;
   - wake detection/false-wake/angular error;
   - provider success, latency, cache rate и bytes.
6. Калибровать score только на отдельном calibration split и сохранять uncertainty.
7. Не объявлять score вероятностью или detector научно подтверждённым до независимого test result.

## P3 — только после P2

- Sentinel-2 B02/B03/B04/B08 on common grid.
- SCL/cloud/shadow/water/glint masks и отдельная optical calibration.
- Dual-polarization/ML расширения только при dataset, baseline и ablation plan.
- ASF SAFE/GRD processing только как отдельный typed processing path.

## Обязательные команды перед каждым merge

```bash
bash -n install_telegram_bot.sh
bash -n deploy_telegram_bot.sh
python -m pytest -q
ruff check src tests
mypy --no-incremental src
python -m build
python runtime_check.py
```

Live provider canary не входит в обычный CI и запускается только явно.
