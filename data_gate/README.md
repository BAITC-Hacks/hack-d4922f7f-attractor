# Data Gate — слой данных

Реализация [docs/05-data-gate.md](../docs/05-data-gate.md) и эндпоинтов Data Gate из
[docs/02-architecture.md](../docs/02-architecture.md) §5. Только стандартная библиотека
Python ≥ 3.10, без сети и без ключей.

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

`DataGateService` уже возвращает API-словари, роутеру остаётся только передать их:

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
- **Идемпотентность**: тот же файл и формат → тот же импорт, без дубликатов.
- **Immutable**: id снимка содержит checksum payload; перезапись другим содержимым — ошибка.
- **Rollback** переключает указатель на предыдущий снимок; журнал и снимки не удаляются.

## Форматы

| `--format` | Схема | Что это |
|---|---|---|
| `source-text-v1` | `city-v1` | Исходное условие задачи в текстовом виде |
| `city-json-v1` | `city-v1` | JSON-снимок города в формате движка |
| `geojson-v1` | `territory-geojson-v1` | Слои территории: районы, здания, дороги, светофоры, зелень. WGS84, у каждого объекта `id` и `properties.layer` |

## Хранилище

`var/data-gate/` (или `AKIM_DATA_GATE_DIR`): `raw/`, `imports/`, `snapshots/`, `refs/`.
Путь по умолчанию отсчитывается от текущего рабочего каталога, включая запуск
установленного пакета. `--store` задаёт хранилище и каталог экспорта bootstrap;
`bootstrap --out` явно переопределяет файл экспорта.
Каталог создаёт собственный `.gitignore` — рантайм-состояние в git не попадает.

Пакет устанавливается через `python -m pip install .` из корня репозитория.
Официальный исходник и JSON-снимок включены в пакет: `python -m data_gate bootstrap`
работает и вне checkout. Для собственного исходника используйте `bootstrap --source FILE`.

## Ещё не реализовано

CSV/XLSX/Parquet-адаптеры, crosswalk границ районов, event/observed/ingested time для
временных рядов V2, импорт обращений, PostgreSQL-хранилище. Порты под них есть:
новый формат — это новый `SourceParser`, новое хранилище — новые репозитории.
