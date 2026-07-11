# Release Gate v0.2

Release gate отделяет воспроизводимый engineering/runtime contract от научной валидации. Закрытый offline CI gate не означает подтверждённый live provider access, успешный deploy на конкретном сервере или доказанную точность detector.

Обозначения:

- `[x]` — проверено текущим кодом и автоматизированным offline test/CI;
- `[ ]` — требует отдельной проверки, внешнего доступа или ещё не реализовано.

## A. Engineering gate

- [x] `bash -n install_telegram_bot.sh` проходит.
- [x] `bash -n deploy_telegram_bot.sh` проходит.
- [x] `python -m pytest -q` проходит без stale tests.
- [x] `ruff check src tests` проходит.
- [x] Контролируемый `mypy --no-incremental src` baseline не растёт относительно актуального `main`; raw debt сохраняется в diagnostics.
- [x] `python -m build` создаёт sdist и wheel.
- [x] `MARINE_TRACK_PROVIDER_PROFILE=core python runtime_check.py` проходит с тестовыми Telegram credentials.
- [ ] CI проверяет весь заявленный Python support matrix и clean constrained install; `LICENSE` соответствует metadata.
- [ ] Clean install на целевом сервере создаёт и запускает рабочий `marine-track.service`.
- [ ] Profile `all` проверен в чистой production-like среде со всеми provider extras.
- [x] Пустой Telegram token останавливает runtime/deploy preflight до restart.
- [ ] Неверный Telegram token фактически отклонён post-switch Telegram healthcheck на целевом сервере с подтверждённым rollback.
- [ ] `/start`, `/menu`, `/status`, `/whoami` проверены после реального systemd deploy.
- [ ] `/dates` и `/detectbbox` проверены после реального systemd deploy и возвращают scene result либо typed provider/materializer failure.
- [x] Preview/archive/search-only asset не передаётся detector как raster.
- [x] Search cache key разделяет абсолютные start/end, purpose/capability и schema contract.
- [x] Search-only cache не используется как detection-capable результат без повторной capability проверки.
- [x] Processable сцены сортируются детерминированно по acquisition time и product id.
- [x] Search/raster cache и materialization используют atomic writes/locks и recovery contract.
- [x] Telegram user state использует полный inter-process read-modify-write `flock`, same-directory temp, file/directory `fsync`, `os.replace`, mode `0600`, corruption quarantine и versioned schema.
- [x] Legacy unversioned Telegram state читается и обновляется без простоя; неизвестная будущая schema fail-closed и не перезаписывается старым release.
- [x] Параллельный multi-process regression test не теряет bbox updates; health проверяет state отдельно без user content или абсолютного пути.
- [x] Пустой `TELEGRAM_ADMIN_IDS` не открывает operational commands; public mode только explicit.
- [x] Scene tokens/callbacks привязаны к user/chat; cross-user replay отклоняется.
- [x] Detection AOI/result/raster/tile/candidate limits применяются до соответствующих дорогих операций.
- [x] Telegram candidate detection выполняется в killable subprocess с wall-clock limit; stalled GDAL/rasterio worker завершается.
- [x] Default Telegram detection использует bounded sector; oversized bbox отклоняется до provider/raster I/O.
- [x] Повторный deploy сохраняет canonical environment, state, cache и versioned release directories по коду и offline tests.
- [x] Production release switch/rollback атомарны по коду; release tree делается read-only для service user.
- [x] Canary/report provenance содержит provider, typed asset/access mode, scene time, AOI hash, code identity, stage durations и очищенную ошибку.
- [x] Sanitizer удаляет bearer/SAS/query tokens, credentials и локальные абсолютные пути из canary/detection errors и reports.

## B. Data-access gate

- [x] CDSE STAC baseline использует `https://stac.dataspace.copernicus.eu/v1/`.
- [x] CDSE collection defaults: `sentinel-1-grd`, `sentinel-2-l2a`.
- [ ] CDSE OData fallback live-проверен на той же AOI/time window.
- [x] Typed `SceneAsset` хранит media type/roles/band/units/nodata/auth/alternates и доступные sidecar metadata.
- [x] Planetary Computer является первым tokenless Sentinel-1 raster path; runtime signing остаётся transient.
- [x] CDSE и Sentinel Hub без полных optional credentials пропускаются до OAuth/network call и не блокируют tokenless fallback.
- [x] Earth Search S1 не используется как безусловно бесплатный operational Sentinel-1 raster path.
- [x] ASF archive/preview assets не считаются processable GeoTIFF/COG до SAFE/GRD processor.
- [x] Provider capability и media type проверяются до materialization.
- [ ] Operational Planetary Computer path прошёл явный live search + signing + TIFF range-read canary на целевом сервере.
- [ ] Detection canary прошёл отдельное operator confirmation, compact AOI и полный materialization/detection path.

## C. Scientific gate

- [ ] Есть scene manifest, data card, positive/negative/uncertain labels и object/wake geometry schema.
- [ ] Есть fixed scene-level/spatial-temporal train/validation/test split без утечки соседних сцен.
- [ ] Есть classical CFAR baseline и формальная error taxonomy.
- [ ] Метрики detection: precision/recall/F1, POD/FAR/CSI, false alarms/km², localization error.
- [ ] Метрики wake: detection rate, false-wake rate, angular error.
- [ ] Метрики speed proxy: bias/MAE/RMSE/coverage against independently paired reference.
- [ ] Метрики стратифицированы по sensor/polarization/incidence/wind/depth/coast/open sea/port/high-clutter.
- [ ] Score калиброван на отдельном calibration split с uncertainty; до этого он остаётся ranking/evidence score, не вероятностью.
- [ ] Kelvin wavelength/speed выдаётся только при applicability/QC/uncertainty и не показывается как подтверждённая скорость.
- [x] Operational single-scene speed по умолчанию имеет `value_knots=null`, `method=not_estimated`; AIS хранится отдельно как external reference.
- [ ] AIS matching полностью закрывает max interpolation gap, one-to-one assignment, ambiguity margin и acquisition-time uncertainty для benchmark.
- [x] Feature units/domain/applicability contract зафиксирован в [`FEATURE_CATALOG.md`](FEATURE_CATALOG.md).

## Проверенный offline-срез — 2026-07-11

Provider canary и bounded detection вошли через PR #29; временная write-capable merge orchestration удалена PR #32. Transactional Telegram user state реализован в PR #30 без временных self-finalization workflow/script.

Полный GitHub Actions gate на implementation head PR #30 завершён успешно:

- shell syntax — passed;
- `ruff` — passed;
- `pytest` — **200 passed**;
- raw mypy — 145 ошибок против 145 на baseline; no-growth gate passed;
- package build — passed, sdist и wheel созданы;
- core `runtime_check.py` — passed.

Этот срез не включает deploy на `us-vmpico`, post-switch Telegram healthcheck и live provider canary. Поэтому offline engineering gate зелёный, но target-host deployment и data-access gates остаются открыты. Научный gate открыт, кроме уже зафиксированных fail-safe semantics.

Следующий один приоритет: fast-forward deploy актуального `main` на `us-vmpico`, зафиксировать release/rollback evidence и только затем явно запустить asset-only provider canary.
