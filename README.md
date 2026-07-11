# Marine Track

Marine Track ищет спутниковые сцены по морской акватории и формирует геопривязанные `vessel_candidate` для последующей проверки оператором.

```text
AOI + UTC interval
→ provider search
→ typed processable raster asset
→ runtime signing/OAuth when required
→ materialization and AOI crop
→ sensor-aware preprocessing
→ candidate detector
→ optional AIS/wake research evidence
→ GeoJSON/CSV/Parquet/report/PNG
→ Telegram
```

Результат не является гарантированной детекцией судна. `ranking_score` и `evidence_score` не являются вероятностью. До независимой калибровки и benchmark каждый объект называется `vessel_candidate`.

## Operational baseline

Основной operational single-raster path — Sentinel-1. Sentinel-2 single-band, Hough/wake и Kelvin speed остаются research paths и по умолчанию выключены.

Для одной спутниковой сцены оперативная скорость по умолчанию имеет вид:

```json
{"speed": {"value_knots": null, "method": "not_estimated"}}
```

AIS хранится как внешний reference после временного и пространственного QC. AIS SOG/COG не заменяет собственную спутниковую оценку. Kelvin wavelength/speed — только research proxy с applicability/QC/uncertainty.

## Доступ к сценам

Для Sentinel-1 candidate detection порядок источников начинается с Planetary Computer. Этот path не требует пользовательского provider token: приложение получает публичный STAC asset и выполняет transient runtime signing. Подписанный URL не сохраняется в registry, report или log.

CDSE и Sentinel Hub являются дополнительными OAuth-провайдерами. При пустых credentials они отключаются до сетевого OAuth-вызова и не блокируют Planetary Computer fallback.

```dotenv
# Optional CDSE
CDSE_ACCESS_TOKEN=
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
CDSE_USERNAME=
CDSE_PASSWORD=

# Optional Sentinel Hub
SENTINELHUB_ACCESS_TOKEN=
SENTINELHUB_CLIENT_ID=
SENTINELHUB_CLIENT_SECRET=
```

Install/deploy выполняются неинтерактивно и не запрашивают provider secrets. Это исключает зависимость автоматического deploy от внешнего OAuth и предотвращает случайную печать секретов. Неполная Sentinel Hub или CDSE username/password конфигурация отклоняется runtime/deploy preflight.

Внешняя доступность каталога, signing endpoint, CDN, quota и конкретного raster asset не может быть гарантирована приложением. При недоступности возвращается typed failure; production flow не подменяет его фиктивными данными или «0 кандидатов».

## Ограничение долгих операций

Telegram detection запускается в отдельном spawned worker process. По умолчанию:

```dotenv
MARINE_TRACK_DEFAULT_DETECTION_SIDE_KM=16
MARINE_TRACK_MAX_DETECTION_AOI_AREA_KM2=400
MARINE_TRACK_DETECTION_JOB_TIMEOUT_S=300
MARINE_TRACK_GDAL_HTTP_CONNECT_TIMEOUT_S=10
MARINE_TRACK_GDAL_HTTP_TIMEOUT_S=45
MARINE_TRACK_GDAL_HTTP_LOW_SPEED_LIMIT_BPS=1024
MARINE_TRACK_GDAL_HTTP_LOW_SPEED_TIME_S=30
MARINE_TRACK_GDAL_HTTP_MAX_RETRY=2
```

Кнопка поиска кандидатов вырезает компактный сектор из default AOI. Пользовательский oversized bbox отклоняется до provider/raster I/O. При превышении wall-clock limit зависший native GDAL/rasterio worker завершается, а Telegram получает явную ошибку вместо бесконечного progress state.

## Установка без Docker

Поддерживаются только `install_telegram_bot.sh`, `deploy_telegram_bot.sh`, systemd и versioned releases.

```bash
cd ~/marine-track
sudo bash install_telegram_bot.sh --prepare-only
sudoedit /etc/marine-track/marine-track.env
sudo bash deploy_telegram_bot.sh
```

Минимально заполните:

```dotenv
TELEGRAM_BOT_TOKEN=<bot-token>
TELEGRAM_ADMIN_IDS=<numeric-telegram-user-id>
MARINE_TRACK_PROVIDER_PROFILE=all
```

`TELEGRAM_ADMIN_IDS` обязателен при стандартном fail-closed режиме. Публичный доступ разрешается только явным `MARINE_TRACK_ALLOW_PUBLIC_BOT=1`.

Canonical paths:

```text
/etc/marine-track/marine-track.env   environment, root:marine-track, 0640
/opt/marine_track/releases/          versioned immutable releases
/opt/marine_track/current            active release symlink
/opt/marine_track/previous           rollback target
/var/lib/marine-track/output         persistent state and outputs
/var/cache/marine-track              persistent cache
```

Deploy сохраняет environment, state, cache и runs вне release directory; создаёт staging venv; выполняет compile/runtime/smoke/health checks; атомарно переключает `current`; после неуспешной post-switch проверки выполняет rollback.

После обновления `main`:

```bash
cd ~/marine-track
git pull --ff-only origin main
sudo bash deploy_telegram_bot.sh
sudo systemctl status marine-track.service --no-pager
```

## Telegram

Основные команды и сценарии:

```text
/start, /menu, /help
/dates, /bboxdates, /areas
/detect, /detectbbox
/output, /status, /whoami
/selftest                    administrator only
```

Scene token, callback и state привязаны к user/chat. Telegram access fail-closed. Выдача может включать overview/crops и GeoJSON/CSV/Parquet/redacted report.

`/selftest` не запускается при deploy, restart или обычном healthcheck. Asset mode выполняет compact AOI → search → typed asset → runtime access → небольшой TIFF range-read. Detection mode требует отдельного подтверждения и оставляет wake/Kelvin выключенными. Подробности: [`docs/PROVIDER_CANARY.md`](docs/PROVIDER_CANARY.md).

## Локальные проверки

```bash
bash -n install_telegram_bot.sh
bash -n deploy_telegram_bot.sh
python -m pytest -q
ruff check src tests
mypy --no-incremental src
python -m build
TELEGRAM_BOT_TOKEN=ci-placeholder \
TELEGRAM_ADMIN_IDS=1 \
MARINE_TRACK_PROVIDER_PROFILE=core \
python runtime_check.py
```

Raw mypy command пока отражает накопленный baseline основного кода. CI дополнительно сравнивает нормализованные fingerprints ошибок с актуальным `main` и запрещает появление или рост ошибок; уменьшение baseline разрешено.

Live provider canary не входит в обычный CI и не запускается автоматически. Его выполняют только явно, при разрешённом внешнем доступе:

```bash
marine-track provider-canary --mode asset
# Full materialization/detection only after separate operator decision:
marine-track provider-canary --mode detection
```

## Реализованные safety/correctness механизмы

- Typed `SceneAsset` и capability-aware selection: preview/archive/search-only asset не передаётся detector.
- Hardened scene-search/raster caches, atomic writes, locks, recovery/quarantine и deterministic ordering.
- Resource limits до дорогих AOI/download/tile/candidate операций.
- Sentinel-1 preprocessing, valid masks, guard-cell CFAR и tiled inference.
- Secret/path/query redaction в provenance, canary reports и Telegram detection failures.
- Atomic systemd release/deploy/rollback с сохранением `.env`, state, cache и output.
- External AIS reference model; operational speed не подменяется AIS или Kelvin proxy.
- Research wake evidence отделено от operational candidate detector и выключено по умолчанию.

## Научные ограничения

Проект ещё не имеет независимого стратифицированного benchmark по open sea, coast, port и offshore/high-clutter. Не завершены fixed scene-level split, object/wake labels, calibration split, uncertainty и метрики precision/recall/F1/POD/FAR/CSI/false alarms per km²/localization error. Поэтому нельзя заявлять подтверждённую точность или вероятность обнаружения.

Sentinel-2 нельзя считать operational до поддержки B02/B03/B04/B08 на общей сетке, SCL/cloud/shadow/water/glint masks и отдельной optical calibration.

Технические документы:

- [`docs/TECHNICAL_SPEC.md`](docs/TECHNICAL_SPEC.md)
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- [`docs/RELEASE_GATE.md`](docs/RELEASE_GATE.md)
- [`docs/FEATURE_CATALOG.md`](docs/FEATURE_CATALOG.md)
- [`docs/AUDIT_2026-07-10.md`](docs/AUDIT_2026-07-10.md)
