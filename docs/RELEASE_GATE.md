# Release Gate v0.1

Перед расширением алгоритмов и новых источников проект должен стабильно пройти эксплуатационный gate первого запуска.

## Обязательные проверки

- [ ] `bash -n install_telegram_bot.sh` проходит.
- [ ] `bash -n deploy_telegram_bot.sh` проходит.
- [ ] `python -m pytest -q` проходит.
- [ ] `ruff check src tests` проходит.
- [ ] Clean install создает рабочий `marine-track-bot.service`.
- [ ] Minimal deploy с provider profile `core` проходит.
- [ ] Full deploy с provider profile `all` проходит или дает понятную ошибку отсутствующих provider-модулей.
- [ ] Пустой Telegram token валит deploy до restart.
- [ ] Неверный Telegram token валит deploy на Telegram healthcheck до restart.
- [ ] `/start`, `/menu`, `/status`, `/whoami` отвечают после запуска сервиса.
- [ ] `/dates sentinel1 12` либо показывает сцены, либо дает понятную provider/search ошибку.
- [ ] `/detectbbox sentinel1 west south east north 12` запускает полный сценарий или дает понятную provider/materializer ошибку.
- [ ] Повторный deploy не скачивает land mask заново, если файл уже есть и force update выключен.
- [ ] Повторные `/dates`, `/bboxdates`, `/detectbbox` используют search/raster cache там, где применимо.

## Правило приоритета

Пока этот gate не закрыт на сервере, не добавлять новые providers, Sentinel-2 full stack, AIS rendering и ASF ZIP/GRD processing.

## Следующий порядок реализации

1. Закрыть фактические ошибки установки и деплоя на сервере.
2. Держать документацию install/deploy синхронизированной с реальным скриптом.
3. Улучшать Telegram UX только если это не ломает release gate.
4. После закрытия gate перейти к режиму выдачи результата: `картинки`, `файлы`, `всё`.
5. Затем добавить lock-файлы для конкурентного raster cache.
6. Затем вернуться к AIS track rendering и Sentinel-2 full stack.
