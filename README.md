# 🌊 Marine Track

[![CI](https://github.com/f2re/marine-track/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/f2re/marine-track/actions/workflows/ci.yml)

Marine Track ищет спутниковые сцены над морской акваторией и формирует геопривязанные `vessel_candidate` для проверки оператором и последующей калибровки.

```text
AOI + UTC interval
→ provider search
→ typed processable raster asset
→ runtime signing/OAuth when required
→ materialization and AOI crop
→ Sentinel-1 preprocessing and valid mask
→ guard-cell CFAR candidate detector
→ optional AIS / research wake evidence
→ GeoJSON / CSV / Parquet / report / PNG
→ Telegram
```

> [!IMPORTANT]
> Результат не является гарантированной детекцией судна. `ranking_score` и `evidence_score` не являются вероятностью. До независимого benchmark каждый объект называется `vessel_candidate`.

## ✅ Текущее состояние

- Основной operational single-raster path — **Sentinel-1**.
- Первый источник Sentinel-1 — **Microsoft Planetary Computer**, пользовательский токен не требуется.
- CDSE, Sentinel Hub, NASA Earthdata/ASF и Copernicus Marine подключаются дополнительно.
- Sentinel-2 single-band, Hough/wake и Kelvin speed — research paths и по умолчанию выключены.
- Telegram-доступ fail-closed; scene tokens, callbacks и state привязаны к user/chat.
- Долгая обработка выполняется в отдельном killable process с ограничением AOI и времени.
- Mutable Telegram state хранится транзакционно: `flock`, temp + `fsync` + `os.replace`, mode `0600`, recovery/quarantine.
- Offline CI проверяет shell syntax, Ruff, pytest, controlled mypy baseline, package build и core runtime check.

> [!WARNING]
> Зелёный CI не подтверждает доступность внешнего каталога, конкретного raster asset или успешный deploy на вашем сервере. Live provider check запускается только явно через asset-only self-test.

<a id="quick-start"></a>
## 🚀 Быстрый запуск

Для первого рабочего запуска нужен только **Telegram Bot Token**. Спутниковые Sentinel-1 сцены будут запрашиваться через tokenless Planetary Computer.

### 1. Склонируйте проект

```bash
git clone https://github.com/f2re/marine-track.git
cd marine-track
git switch main
git pull --ff-only origin main
```

Поддерживаемый production runtime: Linux, Python `>=3.10`, systemd, без Docker.

### 2. Создайте Telegram-бота

1. Откройте официальный [@BotFather](https://t.me/BotFather).
2. Отправьте `/newbot`.
3. Задайте имя и username, заканчивающийся на `bot`.
4. Скопируйте выданный token.

Официальная инструкция Telegram: [From BotFather to “Hello World”](https://core.telegram.org/bots/tutorial).

> [!CAUTION]
> Telegram token равен паролю бота. Не публикуйте его в issue, логах, скриншотах, shell history или Git. При утечке немедленно выполните `/revoke` в @BotFather и выпустите новый token.

### 3. Узнайте свой числовой Telegram user ID

До запуска сервиса отправьте созданному боту любое сообщение, например `/start`. Затем выполните команду — token вводится скрыто и не попадает в shell history:

```bash
read -rsp 'Telegram bot token: ' BOT_TOKEN; echo
curl -fsS "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates" \
  | python3 -c '
import json, sys
payload = json.load(sys.stdin)
ids = {
    item["message"]["from"]["id"]
    for item in payload.get("result", [])
    if isinstance(item.get("message"), dict)
    and isinstance(item["message"].get("from"), dict)
    and isinstance(item["message"]["from"].get("id"), int)
}
print("\n".join(map(str, sorted(ids))) or "ID не найден: сначала отправьте сообщение боту")
'
unset BOT_TOKEN
```

Скопируйте свой ID в `TELEGRAM_ADMIN_IDS`. Для нескольких администраторов используйте запятые: `123456789,987654321`.

### 4. Подготовьте систему и конфигурацию

```bash
sudo bash install_telegram_bot.sh --prepare-only
sudoedit /etc/marine-track/marine-track.env
```

Для минимального запуска достаточно четырёх строк:

```dotenv
TELEGRAM_BOT_TOKEN=123456789:replace_with_real_token
TELEGRAM_ADMIN_IDS=123456789
MARINE_TRACK_PROVIDER_PROFILE=scene
MARINE_TRACK_DEFAULT_SENSOR=sentinel1
```

`scene` — рекомендуемый профиль: устанавливает только scene providers и не тянет необязательный Copernicus Marine stack.

### 5. Разверните release

```bash
sudo bash deploy_telegram_bot.sh
```

Deploy выполняет staging install, compile, runtime/smoke/health checks, создаёт immutable release, атомарно переключает `current`, перезапускает systemd и проверяет Telegram `getMe`. При post-switch failure предусмотрен rollback.

### 6. Проверьте запуск

```bash
sudo systemctl is-active marine-track.service
sudo systemctl status marine-track.service --no-pager
sudo journalctl -u marine-track.service -n 100 --no-pager
```

Откройте бота и отправьте:

```text
/start
/status
/whoami
```

После этого проверьте поиск сроков `/dates`. Полный detection не запускайте до успешного asset self-test.

## 🔑 Где получить все доступы

### Обязательный доступ

| Сервис | Что сделать | Что вставить в environment |
|---|---|---|
| **Telegram Bot API** | [Открыть @BotFather](https://t.me/BotFather) → `/newbot` → скопировать token | `TELEGRAM_BOT_TOKEN` |
| **Telegram administrator ID** | Отправить сообщение боту и выполнить команду из быстрого запуска | `TELEGRAM_ADMIN_IDS` |

### Sentinel-1: работает без дополнительного аккаунта

| Сервис | Авторизация | Настройка |
|---|---|---|
| **Microsoft Planetary Computer** | Не требуется. STAC публичный, SAS URL подписывается transient runtime signing | Ничего не заполнять. [Сервис](https://planetarycomputer.microsoft.com/) · [SAS documentation](https://planetarycomputer.microsoft.com/docs/concepts/sas/) |

> [!TIP]
> Для обычного Sentinel-1 candidate workflow сначала запустите систему только с Telegram token. Добавляйте остальные credentials лишь когда нужен fallback, отдельный provider canary или вспомогательные данные.

### Дополнительные providers

| Сервис | Нажать и получить доступ | Рекомендуемые переменные |
|---|---|---|
| **Copernicus Data Space Ecosystem — CDSE** | [Создать/открыть аккаунт](https://dataspace.copernicus.eu/) · [официальная генерация access token](https://documentation.dataspace.copernicus.eu/APIs/Token.html) | Для постоянной работы: `CDSE_USERNAME`, `CDSE_PASSWORD`, `CDSE_CLIENT_ID=cdse-public`. Для короткого теста: `CDSE_ACCESS_TOKEN` |
| **Sentinel Hub** | [Открыть Dashboard](https://apps.sentinel-hub.com/dashboard/) → User Settings → OAuth clients → Create · [официальная OAuth-инструкция](https://docs.sentinel-hub.com/api/latest/api/overview/authentication/) | `SENTINELHUB_CLIENT_ID`, `SENTINELHUB_CLIENT_SECRET` |
| **NASA Earthdata / ASF DAAC** | [Зарегистрировать Earthdata Login](https://urs.earthdata.nasa.gov/users/new) · [сгенерировать User Token](https://urs.earthdata.nasa.gov/documentation/for_users/user_token) · [открыть ASF Vertex](https://search.asf.alaska.edu/) | Предпочтительно `EARTHDATA_TOKEN`; допустимы `EARTHDATA_USERNAME`, `EARTHDATA_PASSWORD` |
| **Copernicus Marine** | [Зарегистрироваться или войти](https://data.marine.copernicus.eu/register) | `COPERNICUSMARINE_SERVICE_USERNAME`, `COPERNICUSMARINE_SERVICE_PASSWORD`; требуется профиль `all` или `aux` |

> [!NOTE]
> CDSE и Sentinel Hub access tokens короткоживущие. Для постоянного сервиса храните исходные credentials/client secret: Marine Track получает и кеширует access token во время работы. `CDSE_ACCESS_TOKEN` и `SENTINELHUB_ACCESS_TOKEN` удобны только для временной диагностики.

<details>
<summary><b>Готовые блоки environment для optional providers</b></summary>

#### CDSE — рекомендуемый password OAuth

```dotenv
CDSE_ACCESS_TOKEN=
CDSE_CLIENT_ID=cdse-public
CDSE_CLIENT_SECRET=
CDSE_USERNAME=your_cdse_username
CDSE_PASSWORD=your_cdse_password
```

#### Sentinel Hub — рекомендуемый client credentials OAuth

```dotenv
SENTINELHUB_ACCESS_TOKEN=
SENTINELHUB_CLIENT_ID=your_client_id
SENTINELHUB_CLIENT_SECRET=your_client_secret
```

Скопируйте secret сразу после создания OAuth client: Sentinel Hub не показывает его повторно.

#### NASA Earthdata / ASF

```dotenv
EARTHDATA_TOKEN=your_user_token
EARTHDATA_USERNAME=
EARTHDATA_PASSWORD=
```

Earthdata User Token имеет ограниченный срок действия. После истечения выпустите новый token и повторите deploy.

#### Copernicus Marine

```dotenv
MARINE_TRACK_PROVIDER_PROFILE=all
COPERNICUSMARINE_SERVICE_USERNAME=your_username
COPERNICUSMARINE_SERVICE_PASSWORD=your_password
```

</details>

### Источники без token

- **Element 84 Earth Search STAC** — публичный catalog; Sentinel-2 остаётся research-only и выключен по умолчанию.
- **NOAA MarineCadastre AIS** — публичные исторические AIS archives; token не требуется. AIS используется только как внешний reference.
- **Natural Earth** — публичная land/shoreline mask; token не требуется.
- **Локальный AIS CSV** — задаётся через `MARINE_TRACK_AIS_CSV`, сетевой аккаунт не нужен.

## 🧩 Какой provider profile выбрать

| Значение | Что устанавливается | Когда использовать |
|---|---|---|
| `scene` | STAC, Planetary Computer, ASF, Sentinel Hub | **Рекомендуется для первого запуска и Sentinel-1 candidate detection** |
| `all` | `scene` + Copernicus Marine | Нужны спутниковые сцены и auxiliary ocean data |
| `aux` | Только Copernicus Marine | Отдельная подготовка auxiliary data, без scene detection |
| `core` | Без provider extras | Offline tests, диагностика packaging/runtime |

Изменение профиля применяется следующим deploy:

```bash
sudoedit /etc/marine-track/marine-track.env
sudo bash deploy_telegram_bot.sh
```

## 🩺 Безопасная проверка провайдера

Live canary никогда не запускается автоматически при install, deploy, restart или обычном healthcheck.

Сначала выполните только asset mode:

```bash
sudo -u marine-track \
  /opt/marine_track/current/.venv/bin/marine-track \
  provider-canary --mode asset \
  --base-dir /opt/marine_track/current \
  --output-dir /var/lib/marine-track/output
```

Или в Telegram откройте `/selftest` → **Проверить provider и asset**.

Asset mode проверяет:

```text
compact AOI
→ Sentinel-1 provider search
→ typed processable asset
→ transient signing/OAuth
→ bounded TIFF range-read
→ redacted mode-0600 report
```

> [!WARNING]
> `detection` mode дополнительно скачивает/обрезает raster и запускает CFAR. Он требует отдельного подтверждения. Успешный canary подтверждает integration/data access, но не научную точность и не гарантированное наличие `vessel_candidate`.

Подробный контракт: [`docs/PROVIDER_CANARY.md`](docs/PROVIDER_CANARY.md).

## 🤖 Telegram-команды

```text
/start, /menu, /help        — главное меню и справка
/dates                      — доступные сроки сцен для default AOI
/bboxdates                  — сроки по пользовательскому bbox
/areas                      — сохранённые районы
/detect, /detectbbox        — candidate detection
/output                     — картинки / файлы / всё
/status                     — runtime status
/whoami                     — текущий Telegram user ID
/calibrate                  — административная калибровка
/selftest                   — administrator-only provider canary
```

Scene token, callback и mutable state привязаны к user/chat. Публичный бот разрешается только явным `MARINE_TRACK_ALLOW_PUBLIC_BOT=1`; стандартный режим требует `TELEGRAM_ADMIN_IDS`.

## 📦 Результаты

В зависимости от выбранного режима выдачи создаются:

- overview PNG с номерами `vessel_candidate`;
- crop PNG по отдельным кандидатам;
- GeoJSON;
- CSV;
- Parquet;
- redacted `report.json` с provenance и effective config.

Для одной сцены operational speed по умолчанию:

```json
{"speed": {"value_knots": null, "method": "not_estimated"}}
```

AIS SOG/COG хранится отдельно как external reference после временного/пространственного QC. Kelvin wavelength/speed остаётся research-only proxy.

## 🛡️ Ограничение долгих операций

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

Кнопка поиска кандидатов вырезает компактный сектор из default AOI. Oversized bbox отклоняется до provider/raster I/O. При превышении wall-clock limit зависший GDAL/rasterio worker завершается, а Telegram получает явную ошибку.

## 🗂️ Пути production deployment

```text
/etc/marine-track/marine-track.env   credentials/config, root:marine-track, 0640
/opt/marine_track/releases/          versioned immutable releases
/opt/marine_track/current            active release symlink
/opt/marine_track/previous           rollback target
/var/lib/marine-track/output         persistent state and outputs
/var/cache/marine-track              persistent cache
/var/log/marine-track                service logs
```

Deploy не перезаписывает non-empty credentials, state, cache или output при повторном запуске.

## 🛠️ Управление сервисом

```bash
# Состояние
sudo systemctl status marine-track.service --no-pager

# Остановить / запустить / перезапустить
sudo systemctl stop marine-track.service
sudo systemctl start marine-track.service
sudo systemctl restart marine-track.service

# Последние логи
sudo journalctl -u marine-track.service -n 150 --no-pager

# Логи в реальном времени
sudo journalctl -fu marine-track.service
```

### Обновление

```bash
cd ~/marine-track
git switch main
git status --short
git pull --ff-only origin main
sudo bash deploy_telegram_bot.sh
```

`git status --short` перед pull должен быть пустым. Если обновилась только `origin/agent/...`, но `main` сообщает `Already up to date`, feature branch ещё не была слита в `main`.

### Проверка активного release

```bash
readlink -f /opt/marine_track/current
cat /opt/marine_track/current/release.json
sudo /opt/marine_track/current/.venv/bin/python \
  -m marine_track.health \
  --base-dir /opt/marine_track/current \
  --env-file /etc/marine-track/marine-track.env \
  --telegram --json
```

## 🔐 Правила хранения секретов

- Не вставляйте credentials непосредственно в команды shell или URL.
- Используйте `sudoedit /etc/marine-track/marine-track.env`.
- Не коммитьте `.env` и не прикладывайте его к issue.
- Не публикуйте Telegram screenshots с token/error URL.
- После утечки отзовите credential у provider и замените значение в canonical environment.
- Не храните signed URL: они содержат временную query signature.
- Проверяйте права без вывода содержимого:

```bash
sudo stat -c '%a %U:%G %n' /etc/marine-track/marine-track.env
sudo find /var/lib/marine-track/output \
  -name 'telegram_user_state.json*' \
  -exec stat -c '%a %U:%G %n' {} \;
```

## 🧪 Локальные проверки

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

Raw mypy отражает накопленный baseline. CI сравнивает нормализованные error fingerprints с актуальным `main` и запрещает их рост.

## 🧯 Быстрая диагностика

<details>
<summary><b>Бот не запускается</b></summary>

```bash
sudo systemctl status marine-track.service --no-pager
sudo journalctl -u marine-track.service -n 200 --no-pager
sudo grep -E '^(TELEGRAM_ADMIN_IDS|MARINE_TRACK_PROVIDER_PROFILE)=' \
  /etc/marine-track/marine-track.env
```

Не печатайте строку `TELEGRAM_BOT_TOKEN` в публичный лог.

</details>

<details>
<summary><b>Ошибка “No scenes found”</b></summary>

1. Используйте `MARINE_TRACK_DEFAULT_SENSOR=sentinel1`.
2. Увеличьте `MARINE_TRACK_DEFAULT_LOOKBACK_HOURS`, например до `168`.
3. Проверьте AOI: он должен пересекать море и не превышать limits.
4. Запустите asset-only `/selftest`.
5. При недоступности Planetary Computer добавьте CDSE или Sentinel Hub credentials.

Отсутствие processable asset — typed failure, а не «0 судов».

</details>

<details>
<summary><b>Зависло на materialize</b></summary>

Нормальный Telegram detection выполняется в отдельном process и должен завершиться или быть принудительно остановлен по `MARINE_TRACK_DETECTION_JOB_TIMEOUT_S`. Проверьте `journalctl`, уменьшите AOI и убедитесь, что сервер имеет свободное место и доступ к HTTPS.

</details>

<details>
<summary><b>Provider OAuth отключён</b></summary>

Это нормально, если используется Planetary Computer. Для Sentinel Hub заполните одновременно client ID и client secret. Для CDSE заполните username и password либо временный access token. Неполные пары намеренно отклоняются preflight.

</details>

## 🔬 Научные ограничения

Проект ещё не имеет независимого стратифицированного benchmark по open sea, coast, port и offshore/high-clutter. Не завершены fixed scene-level split, полный object/wake label set, calibration split, uncertainty и независимые метрики precision/recall/F1/POD/FAR/CSI/false alarms per km²/localization error.

Sentinel-2 нельзя считать operational до поддержки B02/B03/B04/B08 на общей сетке, SCL/cloud/shadow/water/glint masks и отдельной optical calibration.

## 📚 Документация

- [`docs/TECHNICAL_SPEC.md`](docs/TECHNICAL_SPEC.md) — технический и научный контракт.
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — актуальный план и приоритеты.
- [`docs/RELEASE_GATE.md`](docs/RELEASE_GATE.md) — engineering/data/science gates.
- [`docs/FEATURE_CATALOG.md`](docs/FEATURE_CATALOG.md) — признаки, units, applicability и QC.
- [`docs/PROVIDER_CANARY.md`](docs/PROVIDER_CANARY.md) — live provider self-test.
- [`docs/TELEGRAM_USER_STATE.md`](docs/TELEGRAM_USER_STATE.md) — transactional state и recovery.
- [`docs/AUDIT_2026-07-10.md`](docs/AUDIT_2026-07-10.md) — исходный аудит и root causes.
