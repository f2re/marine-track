# Release Gate v0.3

Release gate отделяет четыре разных утверждения:

1. исходный код и package baseline проходят offline проверки;
2. deploy/rollback воспроизводимы на целевом сервере;
3. operational provider asset действительно доступен через live network path;
4. `vessel_candidate` научно валидирован на независимом benchmark.

Закрытие одного уровня не закрывает остальные. Зелёный CI не подтверждает live provider access или научную точность.

## A. Offline code/package gate

- [x] `bash -n install_telegram_bot.sh` проходит.
- [x] `bash -n deploy_telegram_bot.sh` проходит.
- [x] `python -m pytest -q` проходит; финальный PR #29 gate: 189 tests.
- [x] `ruff check src tests runtime_check.py` проходит.
- [x] controlled `mypy --no-incremental src` baseline запрещает рост ошибок.
- [x] `python -m build` создаёт sdist и wheel.
- [x] `MARINE_TRACK_PROVIDER_PROFILE=core python runtime_check.py` проходит с тестовым Telegram environment.
- [x] CI сохраняет diagnostics для lint/test/mypy/build/runtime gate.
- [x] Временные write-capable PR-finalization workflows и trigger files удалены из `main`.
- [ ] Проверяется полная Python support matrix, clean constrained install и dependency-update job.
- [ ] Dependency lock/constraints policy формально зафиксирована.

Статус A: **закрыт для текущего Python 3.11 offline CI baseline; расширенная compatibility matrix открыта**.

## B. Deploy/runtime gate на целевом сервере

- [ ] Clean install создаёт рабочий `marine-track-bot.service` на контролируемом target host.
- [ ] Пустой Telegram token останавливает deploy до service switch/restart.
- [ ] Невалидный runtime release отклоняется pre-switch checks.
- [ ] `/start`, `/menu`, `/status`, `/whoami` отвечают после deploy.
- [ ] Повторный deploy сохраняет `/etc/marine-track/marine-track.env`, state, cache и runs.
- [ ] Atomic release switch и rollback фактически проверены на target host.
- [ ] Service user не может изменять versioned code/venv release.
- [ ] Corrupt/partial release не оставляет сервис в неопределённом состоянии.

Скрипты и offline checks реализованы, но clean target-host install/deploy/rollback в текущей проверке не выполнялись.

Статус B: **не закрыт**.

## C. Security/state/resource gate

- [x] Пустой `TELEGRAM_ADMIN_IDS` не открывает operational commands; public mode только explicit.
- [x] Scene tokens/callbacks привязаны к owner user/chat; cross-user replay отклоняется.
- [x] Preview/archive/search-only asset не передаётся detector как raster.
- [x] Search cache key учитывает absolute time window и purpose/capability; detection cache revalidates processability.
- [x] Сцены сортируются детерминированно.
- [x] AOI/result/raster/time limits применяются до дорогой materialization.
- [x] Remote detection materialization выполняется в killable worker с wall-clock limit.
- [x] Reports/errors проходят sanitizer; tokens, signed query, credentials и absolute paths не сохраняются.
- [ ] Transactional Telegram user state из PR #30 слит в `main`.
- [ ] Inter-process state lock, fsync/replace, mode `0600`, quarantine и parallel lost-update test подтверждены на актуальном `main`.
- [ ] Полный retention/recovery contract для всех state/cache/report schemas подтверждён integration tests.

Статус C: **частично закрыт; блокер — PR #30 и его integration verification**.

## D. Data-access/provider gate

### Реализовано в коде

- [x] `SceneAsset` хранит typed raster/capability/auth metadata.
- [x] Provider capability и media type проверяются до materialization.
- [x] Planetary Computer является первым tokenless Sentinel-1 detection path.
- [x] CDSE и Sentinel Hub пропускаются до OAuth/network call при отсутствии полного credential contract.
- [x] ASF archive/preview assets не считаются processable raster baseline.
- [x] Asset canary выполняет compact AOI → search → typed asset → signing/OAuth → TIFF range-read.
- [x] Canary report записывается atomic, mode `0600`, redacted, со stage durations и typed failure cause.
- [x] Telegram `/selftest` доступен только администраторам.
- [x] Detection canary требует отдельного подтверждения и принудительно выключает wake/Kelvin research.
- [x] Canary не запускается автоматически при deploy/restart/healthcheck.

### Требуется live verification

- [ ] На target host выполнен explicit asset canary с реальной сетью и сохранён redacted report.
- [ ] Проверен live Planetary Computer catalog + runtime signing + TIFF range-read.
- [ ] Для реально используемого CDSE/Sentinel Hub path проверены credentials, expiry и typed failure behavior.
- [ ] Provider success/latency/bytes/cache outcomes зафиксированы без secrets.
- [ ] Detection canary выполнен только после отдельного разрешения, на малом AOI.

Отсутствие credentials для optional providers не является ошибкой установки: tokenless Planetary Computer используется первым. Доступность внешней сети, каталога и конкретной сцены не может гарантироваться приложением.

Статус D: **code path готов; live data-access gate не закрыт**.

## E. Scientific gate

- [ ] Есть real S1 scene manifest, data card и versioned label schema.
- [ ] Есть positive/negative/uncertain labels, object body и optional wake geometry.
- [ ] Есть fixed scene-level train/validation/test split без spatial/temporal leakage.
- [ ] Метрики detection: precision, recall, F1, POD, FAR, CSI, false alarms/km², localization error.
- [ ] Метрики wake: detection rate, false-wake rate, angular error.
- [ ] Метрики operations: latency, provider success, cache hit и bytes.
- [ ] Score калиброван только на отдельном calibration split с uncertainty.
- [ ] Kelvin wavelength/speed выдаётся только как research proxy с applicability/QC/uncertainty.
- [ ] AIS хранится как внешний reference с temporal/spatial QC и не подменяет satellite evidence.
- [ ] `speed.value_knots=null`, `speed.method=not_estimated` остаются operational default для одной сцены.
- [ ] Sentinel-2 имеет B02/B03/B04/B08 common grid, SCL/cloud/shadow/water/glint masks и отдельную optical calibration.

До закрытия E результат называется только `vessel_candidate`; ranking/evidence score не является вероятностью.

Статус E: **не закрыт**.

## Current audited status — 2026-07-11

- `main` содержит PR #29: provider canary, admin self-test, bounded detection и tokenless fallback.
- PR #31 закрыт как дубликат и не сливался.
- Временная orchestration-инфраструктура удалена отдельным зелёным PR #32.
- PR #30 остаётся открытым и является следующим P0 engineering этапом.
- Offline CI/package gate зелёный.
- Target-host deploy/rollback, explicit live asset canary и scientific benchmark не проверялись и не объявляются успешными.

## Обязательная команда проверки перед merge

```bash
bash -n install_telegram_bot.sh
bash -n deploy_telegram_bot.sh
python -m pytest -q
ruff check src tests
mypy --no-incremental src
python -m build
python runtime_check.py
```

Live canary запускается только явно и не входит в обычный healthcheck.
