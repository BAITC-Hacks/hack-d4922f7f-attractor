# Data Gate — слой данных

Реализация [docs/05-data-gate.md](../docs/05-data-gate.md) и эндпоинтов Data Gate из
[docs/02-architecture.md](../docs/02-architecture.md) §5. Python ≥ 3.11, без сети и
без ключей. Основные адаптеры используют стандартную библиотеку; XLSX — `openpyxl`.
HTTP adapter использует зависимости из основного README.

```text
Источник → raw → проверка → staging → нормализация → quality report
         → preview изменений → публикация immutable snapshot → эксперимент
```

## Быстрый старт

```bash
python -m data_gate bootstrap
```

Берёт исходное условие `data/source-dataset.ru.txt`, разбирает его, проверяет качество,
публикует снимок `official-v1` и выгружает payload для движка в
`var/data-gate/exports/official-v1.snapshot.json`. Повторный запуск идемпотентен.

Снимок совпадает с `data/v1/official-v1.snapshot.json` из слоя симуляции по всем полям,
которые читает движок, и дополнительно несёт названия мер, профили районов и каталог
показателей для интерфейса и AI. Движок V1 на этом снимке даёт контрольные
**52.55768** и **56.54307** — это проверяет `tests/data_gate/test_engine_contract.py`.

```bash
python -m unittest discover -s tests -t .
```

## Слои (clean architecture)

| Каталог | Что внутри | Зависит от |
|---|---|---|
| `domain/` | Паспорт набора, отчёт качества, правила качества, preview, checksum | ничего |
| `application/` | `DataGateService` и порты (`SourceParser`, репозитории, `Clock`) | domain |
| `infrastructure/` | Адаптеры форматов, файловое и in-memory хранилища, часы | domain, ports |
| `composition.py` | Сборка зависимостей: `create_file_gate()`, `create_memory_gate()` | всё |
| `__main__.py` | CLI; печатает тот же JSON, что отдаст HTTP API | composition |

## Для HTTP API

Маршруты реализованы в `services/api/app.py` и закрыты admin bearer token.
Пользовательские импорты не могут заменять `official-v1`:

| Эндпоинт | Метод сервиса | Схема ответа |
|---|---|---|
| `POST /datasets/imports` | `create_import(bytes, format, PassportInput)` | `packages/contracts/data-gate-import.report.schema.json` |
| `GET /datasets/imports/{id}/report` | `get_report(id)` | то же, с `preview` |
| `POST /datasets/imports/{id}/publish` | `publish(id, accepted_warnings)` | `packages/contracts/data-gate-snapshot.manifest.schema.json` |
| — | `rollback(dataset_id)`, `current_snapshot`, `get_snapshot`, `list_*` | — |

Ошибки — подклассы `DataGateError` с `to_api_dict()` → `{code, field, message}`:
`unsupported_format`, `source_parse_error`, `invalid_passport`, `import_not_found`,
`snapshot_not_found`, `publish_blocked`, `nothing_to_rollback`, `immutability_violation`.

Слою симуляции нужен только payload:
`gate.current_snapshot("official-v1").payload` — тот же формат, что `engine/v1` читает
через `load_snapshot`.

## Правила, как в docs/05

- **Критическая ошибка блокирует публикацию.** Схема, типы, уникальность id, сумма весов
  и долей населения = 1, шкала 0–100, лаг в пределах горизонта, ссылочная целостность
  синергий, конфликтов и эффектов.
- **Предупреждение требует явного допущения**: `publish(id, accepted_warnings=[...])`,
  коды попадают в manifest снимка.
- **Пропуск не равен нулю**: `null` в показателе — критическая ошибка, а не 0.
- **Ничего не чинится молча.** Контрольные числа источника («Итог D», базовый Score)
  идут в сверку, а не в модель. Итог D всех районов сверяется с расчётом по весам.
- **Неизвестные поля** остаются в raw и перечислены в `mapping.unmapped`, на модель не влияют.
- **Идемпотентность**: те же байты, формат, паспорт и transform version → тот же импорт.
- **Immutable**: id снимка зависит от payload, паспорта и принятых warnings;
  checksum staging и снимка проверяется при чтении.
- **Rollback** переключает указатель на предыдущий снимок; журнал и снимки не удаляются.

## Форматы

| `--format` | Схема | Что это |
|---|---|---|
| `source-text-v1` | `city-v1` | Исходное условие задачи в текстовом виде |
| `city-json-v1` | `city-v1` | JSON-снимок города в формате движка |
| `geojson-v1` | `territory-geojson-v1` | Слои территории: районы, здания, дороги, светофоры, зелень. WGS84, у каждого объекта `id` и `properties.layer` |
| `v2-city-json` | `v2-city-v1` | Синтетический составной снимок V2: произвольные районы, население, агрегированные дороги, школа, жильё, бригады, погода и начальные деньги |
| `observations-json-v1` | `observations-v1` | Временные ряды в объекте `{"records": [...]}` с единицами, смыслом показателя, тремя временами и происхождением |
| `csv-v1` | `observations-v1` | UTF-8 CSV; по умолчанию первая строка — заголовки, разделитель — запятая |
| `xlsx-v1` | `observations-v1` | XLSX; по умолчанию первый лист, первая строка — заголовки; формулы и макросы запрещены |

### V2: снимок, времена и пропуски

`engine.v2.infrastructure.datasets.load_demo_snapshot(gate)` публикует шестирайонный
синтетический снимок через те же импорт, quality report и immutable-хранилище.
Версия V1 остаётся отдельным набором. Изменение текущего указателя не меняет старый
снимок, на который ссылается запущенный эксперимент.

Табличная строка содержит `id`, `districtId`, `metric`, `value`, `unit`,
`measureKind` (`stock/flow/rate`), `statistic` (`total/mean/median/p90/proportion`),
`sourceType` и три ISO-8601 времени с часовым поясом: `eventTime`, `observedAt`,
`ingestedAt`. Для flow обязательны `periodStart` и `periodEnd` — месячный поток
обращений не превращается автоматически в очередь. Значение `null` или пустая
ячейка остаётся пропуском, а не нулём. `estimated` требует объекта
`imputation: {"field":"value","method":"group-median","parameters":{...}}`.
В CSV/XLSX этот объект передаётся строкой JSON. Автоматической импутации нет.

`observations_available_at(payload, cutoff)` выбирает только записи, которые были
наблюдены **и** загружены не позднее cutoff. Это фильтр доступности, а не фильтр
времени события: заранее доступный прогноз может описывать будущее событие.
Входное `ingestedAt` — время загрузки исходной системы; фактическая загрузка в этот
Data Gate дополнительно сохраняется как `ImportRecord.createdAt`.

Выбор листа и заголовка в Python-адаптере:

```python
from data_gate.infrastructure.parsers import CsvParser, XlsxParser

csv_parser = CsvParser(header_row=2, delimiter=";")
xlsx_parser = XlsxParser(sheet="observations", header_row=3)
```

Настроенные адаптеры можно передать в `DataGateService(parsers=...)`; основной HTTP
импорт использует настройки по умолчанию. Лимиты: 10 MiB входа, 100 000 строк,
100 колонок; для XLSX дополнительно ограничен распакованный размер. Содержимое
файлов не выполняется; формулы отклоняются, внешние связи не загружаются.

Схема `v2-city-v1` — явный demo-контракт, **не** универсальная реализация всех
16 предметных схем из ТЗ. Калиброванные источники и преобразование независимых
наблюдений в составной городской снимок требуют отдельных адаптеров.

## Хранилище

`var/data-gate/` (или `AKIM_DATA_GATE_DIR`): `raw/`, `imports/`, `snapshots/`, `refs/`.
Путь по умолчанию отсчитывается от текущего рабочего каталога, включая запуск
установленного пакета. `--store` задаёт хранилище и каталог экспорта bootstrap;
`bootstrap --out` явно переопределяет файл экспорта.
Каталог создаёт собственный `.gitignore` — рантайм-состояние в git не попадает.

Один процесс-писатель: lock HTTP не защищает от CLI
или второго worker.

### Миграция data-gate/1.1.0

Новая identity учитывает паспорт: раньше новый источник при тех же байтах терялся.
Старые записи не удаляются, читаются по прежним ID. Повторный импорт создаёт новую
запись с новой identity. Raw checksum относится к точным байтам: CRLF/LF дают
разное происхождение при одинаковом нормализованном payload и результате.

Пакет устанавливается через `python -m pip install .` из корня репозитория.
Официальный исходник и JSON-снимок включены в пакет: `python -m data_gate bootstrap`
работает и вне checkout. Для собственного исходника используйте `bootstrap --source FILE`.

## Ещё не реализовано

Parquet-адаптер, crosswalk границ районов, предметные адаптеры всех 16 схем ТЗ,
дедупликация обращений, PostgreSQL-хранилище. Порты под них есть:
новый формат — это новый `SourceParser`, новое хранилище — новые репозитории.
