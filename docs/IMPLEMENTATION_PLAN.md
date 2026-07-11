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

### Реализовано в release candidate

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
- [x] Transactional Telegram user state: complete read-modify-write `flock`, same-directory temp, file/directory `fsync`, `os.replace`, mode 0600 и exactly one trailing newline.
- [x] Corrupt active user state сохраняется в private quarantine; legacy schema читается и обновляется; unknown future schema fail-closed.
- [x] Separate redacted user-state health и multi-process lost-update regression test.
- [x] Временные write-capable PR-finalization workflows/scripts отсутствуют в итоговых diffs.

Provider canary и bounded detection вошли через PR #29; cleanup orchestration удалена PR #32. PR #30 обновлён от актуального `main` и содержит только runtime/tests/docs изменения transactional state.

Полный offline gate implementation head PR #30: shell/ruff/**200 tests**/build/core runtime/no-growth mypy passed; raw mypy остаётся 145 ошибок против 145 на baseline.

### Не подтверждено

- [ ] Clean install и atomic deploy на `us-vmpico` после обновления `main`.
- [ ] Post-switch Telegram healthcheck и rollback на реальном systemd service.
- [ ] Сохранение и migration реального `telegram_user_state.json` при target-host deploy подтверждены оператором.
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
| Telegram mutable state transactional | `telegram_user_state.py` transaction/lock/quarantine/schema contract | multi-process, recovery, permission и health tests | `TELEGRAM_USER_STATE.md` | закрыто offline |
| Live provider/data access | explicit asset canary | не запускался | release gate | открыто |
| Научная точность | dataset/evaluation/calibration workflow | benchmark отсутствует | technical spec/catalog | открыто |

## P0 — завершение target-host engineering gate

### P0.1. Deployment актуального `main`

1. Обновить server checkout fast-forward от `origin/main`; зафиксировать до/после SHA.
2. Запустить `deploy_telegram_bot.sh`; зафиксировать release id/code SHA.
3. Проверить `systemctl is-active`, runtime/health output и сохранение canonical env/state/cache/output.
4. Проверить, что существующий `telegram_user_state.json` не потерян, имеет mode 0600 после доступа/mutation и health не раскрывает user content/path.
5. Проверить `/start`, `/status`, `/dates` и bounded `/detectbbox`.
6. Смоделировать безопасный post-switch failure только контролируемым способом и подтвердить rollback, не повреждая production state.
7. Не запускать live canary автоматически.

### P0.2. Explicit asset-only provider canary

После успешного deploy и только по явному разрешению:

```text
compact AOI
→ Sentinel-1 search
→ typed processable asset
→ transient Planetary Computer signing
→ bounded TIFF range-read
→ redacted mode-0600 report
```

Не запускать detection mode до отдельного подтверждения. Live success подтверждает integration/data access, а не научную точность или гарантированное наличие `vessel_candidate`.

### P0.3. Контролируемый typing/packaging baseline

- [x] Exact raw `mypy --no-incremental src` сохраняется в diagnostics.
- [x] CI сравнивает нормализованные error fingerprints с актуальным `main` и запрещает рост.
- [ ] Последовательно уменьшать raw debt без широких `ignore_errors`.
- [ ] Добавить Python 3.10/3.11/3.12 support matrix и clean constrained install.
- [ ] Проверить license metadata и reproducible dependency/constraints policy.

## P1 — эксплуатационная проверяемость после server gate

### P1.1. Provider/runtime evidence

- Сохранять latency по stages, provider success/failure class, bytes checked/downloaded и cache hit.
- Проверять expired signing/OAuth и повторный запуск.
- Проверять сохранение `.env`, state, cache и outputs при deploy/rollback.
- Не логировать credentials, signed query, local absolute paths или user content.
- Проверять recovery после corrupt state только на копии/fixture, не повреждая production state.

### P1.2. State retention and operations

- Зафиксировать retention/quarantine cleanup policy для historical corrupt snapshots.
- Проверить concurrent callbacks на целевом filesystem, включая restart во время queued updates.
- Сохранять unknown future schema fail-closed: старый release не должен перезаписывать state после rollback с более новой schema.

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
