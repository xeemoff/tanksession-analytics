# Быстрый старт — TankSession Analytics 0.4.0-rc3

## Посмотреть демо

Нужны Python 3.9+ и браузер. На Windows дважды нажми **demo_dashboard.cmd**. Через терминал:

```powershell
python tools/launch_dashboard.py --demo
```

Браузер откроется после запуска локального сервера. На странице явно отмечены **вымышленные данные**: 48 боёв и две цели аккаунта `demo`. Посмотри фильтры, сравнение периодов, график и CSV. При окне 30 или 100 боёв данных демо недостаточно для сравнения двух полных периодов — панель объяснит это.

## Открыть свою историю

На Windows запусти **start_dashboard.cmd** и выбери корневую папку игры с `paths.xml`. Если диалог недоступен:

```powershell
python tools/launch_dashboard.py --game-dir "D:\Games\Tanki"
```

Либо укажи точный путь, который игровой адаптер записал в `python.log`:

```powershell
python tools/launch_dashboard.py --data "D:\your-folder\battles.jsonl"
```

Помощник не устанавливает мод и не создаёт вымышленные бои в твоём журнале. Пока файла нет, страница показывает ожидание. После записи результата обнови страницу. Ошибка доступа отображается отдельно, старые данные при ней не выдаются за успешно прочитанные.

При занятом порте добавь `--port 0`. Чтобы открыть адрес вручную, добавь `--no-browser`. Для остановки нажми `Ctrl+C` в консоли.

## Цели

```powershell
python tools/launch_dashboard.py --data "D:\your-folder\battles.jsonl" --goals "D:\your-folder\goals.json"
```

В JSON укажи точное название танка из истории, `window` и `target_avg_damage`. Необязательный `account_id` привязывает цель к аккаунту. Без него один шаблон оценивается отдельно для каждого аккаунта. Пример в `sample_data/goals.json` привязан к вымышленному `demo`, поэтому для собственной истории создай свой файл.

## Проверить проект

```powershell
python -m unittest discover -s tests -v
python tools/simulate_capture.py
python tools/benchmark.py --battles 100000
```

Два теста настоящей Python 2.7 сборки пропускаются без переменной `PYTHON2`; в отдельном CI job они выполняются с собранным CPython 2.7.18. Отдельно проверяется Windows, HTTP-панель и восстановление журнала.

## Проверить мод в игре

**Совместимость с актуальным клиентом ещё не подтверждена.** Успешный CI и пакет `.mtmod` не заменяют такую проверку.

Используй [пошаговый тест-план](docs/CHECK_CLIENT_RU.md) и [протокол совместимости](docs/CLIENT_VALIDATION_RU.md). Артефакт успешной CI-сборки содержит пакет и SHA-256. Локальная сборка требует отдельного CPython 2.7:

```powershell
python tools/build.py --python2 "C:\Python27\python.exe"
```

Пакет создаётся в `dist/ru.tanksession.analytics_0.4.0-rc3.mtmod`. Автоматической установки нет. Восстановление через игровой кэш остаётся выключенным до проверки его API.

Для обсуждения неисправностей достаточно версии клиента, описания сценария и обезличенных счётчиков:

```powershell
python tools/diagnose_log.py --log "D:\your-folder\python.log" --json
```

## Обслужить историю

Проверка без изменения файла:

```powershell
python tools/maintain_data.py --data "D:\your-folder\battles.jsonl"
```

Для компактирования добавь `--compact`, предварительно **закрыв игру и панель**. Резервная копия исходных байтов остаётся рядом. Не запускай несколько записывающих клиентов с одним журналом.

[README](README.md) · [Архитектура](docs/ARCHITECTURE_RU.md) · [Публикация](docs/PUBLICATION_RU.md)
