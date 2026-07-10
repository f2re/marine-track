# Release Gate v0.2

Release gate отделяет «код запускается» от «метод научно подтверждён». До закрытия engineering gate нельзя объявлять detector operational и расширять алгоритмы ради новых функций.

## A. Engineering gate

- [ ] `bash -n install_telegram_bot.sh` проходит.
- [ ] `bash -n deploy_telegram_bot.sh` проходит.
- [ ] `python -m pytest -q` проходит без stale tests.
- [ ] `ruff check src tests` проходит.
- [ ] `mypy` baseline отделяет optional-stub debt от реальных ошибок и не ухудшается.
- [ ] CI проверяет заявленный Python support matrix и clean constrained install; `LICENSE` соответствует metadata.
- [ ] Clean install создаёт рабочий `marine-track-bot.service`.
- [ ] `MARINE_TRACK_PROVIDER_PROFILE=core` runtime check проходит с тестовым token.
- [ ] Profile `all` либо проходит, либо явно сообщает отсутствующие optional provider modules/credentials.
- [ ] Пустой Telegram token останавливает deploy до restart.
- [ ] Неверный Telegram token останавливает deploy на healthcheck до restart.
- [ ] `/start`, `/menu`, `/status`, `/whoami` отвечают после запуска.
- [ ] `/dates` и `/detectbbox` возвращают сцены или typed provider/materializer error.
- [ ] Preview/archive-only asset никогда не передаётся detector как raster.
- [ ] Search cache key содержит абсолютные start/end, purpose/capability, filters, provider/config fingerprint и schema version.
- [ ] `/dates` cache не может быть использован `/detectbbox` без detection-capability/readability revalidation.
- [ ] Самая свежая сцена выбирается детерминированной сортировкой, а не случайным порядком provider response.
- [ ] Search/raster cache atomic; параллельная загрузка одного asset защищена lock-файлом.
- [ ] Registry/user-state пишутся atomic/locked, имеют schema version, recovery и полный retention contract.
- [ ] Пустой `TELEGRAM_ADMIN_IDS` не открывает operational commands; public mode только explicit.
- [ ] Scene tokens/callbacks привязаны к user/chat; cross-user replay отклоняется.
- [ ] До provider/download применяются AOI/interval/result/bytes/time и per-user rate/concurrency limits.
- [ ] Повторный deploy не перезаписывает `.env`, runs и готовую land mask.
- [ ] Production code/venv read-only для service user; release switch/rollback атомарны.
- [ ] Отчёт содержит provider, collection, typed asset, CRS/GSD, scene time interval, effective config, code commit и очищенные ошибки.
- [ ] Logs/report не содержат bearer/SAS/query tokens, credentials, AIS path и абсолютные server paths.

## B. Data-access gate

- [ ] CDSE STAC использует `https://stac.dataspace.copernicus.eu/v1/`.
- [ ] CDSE collections: `sentinel-1-grd`, `sentinel-2-l2a`.
- [ ] CDSE OData fallback проверен на той же AOI/time window.
- [ ] CDSE typed assets сохраняют media type/roles/band/units/nodata/auth/alternates и calibration/noise sidecars.
- [ ] Planetary Computer auth/SAS preflight проверен отдельно от public catalog search.
- [ ] Earth Search S1 не считается credentials-free: requester-pays S3 path либо проходит credential/cost canary, либо остаётся disabled.
- [ ] ASF явно помечен как archive/preview до SAFE/GRD processing.
- [ ] Provider capability и media type проверяются до materialization.
- [ ] Operational provider path проходит live sign + range-read canary; offline import/config preflight не считается readiness.

## C. Scientific gate

- [ ] Есть scene manifest, labels, negative scenes и data card.
- [ ] Есть fixed scene-level/spatial-temporal train/validation/test split.
- [ ] Есть classical CFAR baseline и error taxonomy.
- [ ] Метрики detection: precision/recall/F1, POD/FAR/CSI, false alarms/km², localization error.
- [ ] Метрики wake: detection rate, false-wake rate, angular error.
- [ ] Метрики speed: bias/MAE/RMSE/coverage against paired AIS/reference.
- [ ] Метрики стратифицированы по sensor/polarization/incidence/wind/depth/coast/open sea.
- [ ] `confidence` calibrated on a held-out calibration split; до этого это `evidence_score`.
- [ ] Kelvin wavelength выдаётся только при applicability/QC/uncertainty.
- [ ] AIS/Ocean context не подменяют отсутствие спутникового признака.
- [ ] AIS matching имеет max interpolation gap, one-to-one assignment, ambiguity margin и acquisition-time uncertainty.
- [ ] `speed.value`/Kelvin proxy/AIS SOG и heading axis/direction хранятся раздельно.
- [ ] Feature units/domain/applicability соответствуют [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md).

## Current audit status (2026-07-10)

- Engineering: **не закрыт** — 77 tests passed, 4 failed; ruff reports 2 import-order errors; последний CI остановился на lint, test job пропущен; `mypy --no-incremental` даёт 74 ошибки.
- Correctness/security: **не закрыт** — search cache коллидирует по времени/capability, Telegram auth fail-open при пустом allowlist, scene tokens не user-scoped.
- Data access: **не закрыт** — CDSE provider hard-codes deprecated STAC endpoint/legacy collection names и теряет asset/auth/sidecar metadata.
- Scientific: **не закрыт** — benchmark, labels, calibration and uncertainty отсутствуют.

Подробности и приоритеты: [`AUDIT_2026-07-10.md`](AUDIT_2026-07-10.md), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
