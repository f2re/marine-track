# План реализации Marine Track

План разделяет три независимых результата:

1. воспроизводимый и безопасный engineering baseline;
2. подтверждённый доступ к реальным provider assets на целевом сервере;
3. научную валидацию `vessel_candidate` на независимом benchmark.

Зелёный CI не закрывает live data-access gate и не подтверждает точность детектора.

## Срез состояния на 2026-07-11

Основная ветка: `main`.

Проверенный SHA после P0 merge и удаления временной orchestration-инфраструктуры:

```text
b128873d6e443cedc7628312babae12323fb9d62
```

PR #29 с provider canary, bounded detection и tokenless fallback слит. Дублирующий PR #31 закрыт. PR #30 с transactional Telegram user state остаётся отдельным открытым изменением и не считается реализованным в `main`.

### Матрица требований

| Требование | Реализация в `main` | Проверка | Документация | Статус |
|---|---|---|---|---|
| Typed processable raster asset; preview/archive не передавать detector | `SceneAsset`, capability-aware search, `select_processing_asset`, typed materialization errors | offline provider/materializer tests | `TECHNICAL_SPEC.md`, `PROVIDER_CANARY.md` | Реализовано |
| Бесплатный путь без Sentinel Hub/CDSE credentials | Planetary Computer первым в S1 detection order; optional OAuth providers пропускаются до network call | `test_provider_fallback_safety.py` | README, `PROVIDER_CANARY.md` | Реализовано в коде; live availability не подтверждена |
| Не зависать на remote COG/GDAL | отдельный killable process, wall-clock timeout, GDAL HTTP/low-speed limits | `test_bounded_detection.py`, Telegram safety tests | README | Реализовано |
| Ограничить дорогие операции заранее | bounded default AOI, detection AOI area limit, общие AOI/result/raster limits | provider fallback/resource-limit tests | README, `TECHNICAL_SPEC.md` | Реализовано |
| Explicit S1 provider canary | CLI `provider-canary`, admin-only Telegram `/selftest`, asset/detection modes, redacted mode-0600 report | `test_provider_canary.py`, `test_telegram_selftest.py` | `PROVIDER_CANARY.md` | Реализовано; live canary не запускался |
| Search/cache correctness | absolute time/capability-aware keys, typed cache payloads, deterministic ordering and revalidation | cache/provider regression tests | `TECHNICAL_SPEC.md` | Реализовано |
| Fail-closed Telegram access и user/chat-scoped scene tokens | allowlist/public flag contract, owner-bound registry/callback validation | access/replay tests | README | Реализовано |
| Transactional Telegram user state | inter-process lock, fsync/replace, quarantine, parallel lost-update test | находится в PR #30 | будет обновлено вместе с PR #30 | Не слито |
| Atomic versioned deploy/rollback с сохранением данных | install/deploy scripts, versioned releases, pre-switch runtime/health checks | shell syntax, package build, core runtime check; target-host clean install не выполнялся в этой сессии | README | Код готов; серверная проверка открыта |
| Научно валидированный detector | scene manifest, labels, fixed split, metrics, calibration uncertainty | отсутствует независимый benchmark | `FEATURE_CATALOG.md` | Не реализовано |

## Что фактически закрыто

### P0-A. CI и package/runtime baseline

- [x] `bash -n install_telegram_bot.sh`.
- [x] `bash -n deploy_telegram_bot.sh`.
- [x] `python -m pytest -q`.
- [x] `ruff check src tests runtime_check.py`.
- [x] controlled `mypy --no-incremental src` no-growth gate.
- [x] `python -m build` для sdist и wheel.
- [x] `python runtime_check.py` в `core` provider profile с тестовым Telegram environment.
- [x] временные PR-finalization workflows и trigger files удалены из `main`.

Финальный PR #29 gate прошёл 189 offline tests. Live network tests не входят в обычный CI.

### P0-B. Provider/materialization safety

- [x] typed provider assets и capability filtering;
- [x] runtime signing/OAuth остаются transient и не сохраняются в reports;
- [x] Planetary Computer используется как tokenless S1 fallback;
- [x] CDSE/Sentinel Hub не вызываются без полного credential contract;
- [x] remote materialization выполняется в ограниченном worker process;
- [x] отсутствие processable asset возвращает typed failure, а не «0 кандидатов»;
- [x] asset canary делает только compact AOI search/sign/range-read;
- [x] detection canary требует отдельного подтверждения и выключает wake/Kelvin research.

### P0-C. Честная пользовательская семантика

- [x] основной объект результата — `vessel_candidate`;
- [x] ranking/evidence score не называется вероятностью;
- [x] operational speed по одной сцене по умолчанию: `value_knots=null`, `method=not_estimated`;
- [x] AIS хранится как внешний reference;
- [x] Kelvin speed остаётся research-only proxy;
- [x] Sentinel-2 single-band path остаётся experimental и выключен по умолчанию.

## Открытый engineering/data-access gate

### P0-1. Transactional Telegram state

Продолжить и довести до зелёного состояния существующий PR #30, не создавать дубликат. Перед merge проверить:

- inter-process lock;
- temp file + flush + `fsync` + `os.replace`;
- mode `0600`;
- quarantine повреждённого JSON;
- schema/version recovery;
- parallel lost-update regression test;
- отсутствие cross-user state leakage.

### P0-2. Target-host deploy verification

На чистом или контролируемом серверном окружении проверить:

1. install и deploy без Docker;
2. создание и запуск `marine-track-bot.service`;
3. pre-switch runtime/health checks;
4. atomic release switch и rollback;
5. сохранение `/etc/marine-track/marine-track.env`, state, cache и runs;
6. повторный deploy и rollback после искусственно невалидного release.

Нельзя считать этот пункт закрытым только по bash syntax или package build.

### P0-3. Explicit live provider asset canary

После отдельного разрешения оператора и при доступной сети выполнить только asset mode:

```bash
marine-track provider-canary --mode asset
```

или admin-only Telegram `/selftest` → asset canary.

Проверить compact AOI → S1 search → typed raster asset → runtime signing/OAuth → TIFF range-read и сохранить redacted report. Canary не должен автоматически запускаться при deploy, restart или обычном healthcheck.

Detection mode разрешается только отдельным подтверждением, на малом AOI, с wake/Kelvin research выключенными.

## P1. Эксплуатационная проверяемость после engineering gate

- агрегировать provider success/failure, stage latency, bytes and cache outcomes без secrets;
- проверить expired auth, provider fallback и range-read failures на controlled fixtures;
- зафиксировать data-access matrix по каждому реально используемому provider path;
- проверить cleanup/retention для registry, search/raster cache, reports и Telegram outputs;
- не добавлять новые providers или ML-модели до закрытия текущего gate.

## P2. Научная валидация

После engineering/data-access gate:

1. собрать real S1 scene manifest и data card;
2. стратифицировать open sea, coast, port и offshore/high-clutter;
3. разметить positive/negative/uncertain, object body и optional wake geometry;
4. сделать fixed scene-level train/validation/test split без leakage соседних сцен;
5. добавить evaluation CLI;
6. считать precision, recall, F1, POD, FAR, CSI, false alarms/km² и localization error;
7. отдельно считать wake detection/false-wake/angular error;
8. измерять latency, provider success, cache hit и bytes;
9. калибровать score только на отдельном calibration split и сохранять uncertainty.

До этого результат нельзя называть гарантированной детекцией судна или вероятностью.

## Обязательная проверка перед следующим merge

```bash
bash -n install_telegram_bot.sh
bash -n deploy_telegram_bot.sh
python -m pytest -q
ruff check src tests
mypy --no-incremental src
python -m build
python runtime_check.py
```

Live canary запускается только явно; обычный CI использует offline fixtures/mocks.

## Следующий один приоритетный этап

Довести существующий PR #30 с transactional Telegram state до зелёного состояния и слить его после повторной синхронизации с актуальным `main`.
