# Release Gate v0.2

Release gate отделяет «код запускается» от «метод научно подтверждён». До закрытия engineering gate нельзя объявлять detector operational и расширять алгоритмы ради новых функций.

## A. Engineering gate

- [ ] `bash -n install_telegram_bot.sh` проходит.
- [ ] `bash -n deploy_telegram_bot.sh` проходит.
- [ ] `python -m pytest -q` проходит без stale tests.
- [ ] `ruff check src tests` проходит.
- [ ] Clean install создаёт рабочий `marine-track-bot.service`.
- [ ] `MARINE_TRACK_PROVIDER_PROFILE=core` runtime check проходит с тестовым token.
- [ ] Profile `all` либо проходит, либо явно сообщает отсутствующие optional provider modules/credentials.
- [ ] Пустой Telegram token останавливает deploy до restart.
- [ ] Неверный Telegram token останавливает deploy на healthcheck до restart.
- [ ] `/start`, `/menu`, `/status`, `/whoami` отвечают после запуска.
- [ ] `/dates` и `/detectbbox` возвращают сцены или typed provider/materializer error.
- [ ] Preview/archive-only asset никогда не передаётся detector как raster.
- [ ] Search/raster cache atomic; параллельная загрузка одного asset защищена lock-файлом.
- [ ] Повторный deploy не перезаписывает `.env`, runs и готовую land mask.
- [ ] Отчёт содержит provider, collection, asset, CRS/GSD, effective config, code commit и ошибки.

## B. Data-access gate

- [ ] CDSE STAC использует `https://stac.dataspace.copernicus.eu/v1/`.
- [ ] CDSE collections: `sentinel-1-grd`, `sentinel-2-l2a`.
- [ ] CDSE OData fallback проверен на той же AOI/time window.
- [ ] Planetary Computer auth/SAS preflight проверен отдельно от public catalog search.
- [ ] ASF явно помечен как archive/preview до SAFE/GRD processing.
- [ ] Provider capability и media type проверяются до materialization.

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

## Current audit status (2026-07-10)

- Engineering: **не закрыт** — 77 tests passed, 4 failed; ruff reports 2 import-order errors.
- Data access: **не закрыт** — CDSE provider hard-codes deprecated STAC endpoint/legacy collection names.
- Scientific: **не закрыт** — benchmark, labels, calibration and uncertainty отсутствуют.

Подробности и приоритеты: [`AUDIT_2026-07-10.md`](AUDIT_2026-07-10.md), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md).
