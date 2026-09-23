# Контракты

- `v1-*.schema.json` — исходные framework-independent запрос/ответ application layer.
  Формат существующих схем сохранён; их проверяют golden/HTTP tests.
- `openapi.json` — исполняемый HTTP-контракт текущей версии, включая схемы запросов,
  evaluate/validate/alternatives/analysis. Источник: Pydantic-модели и маршруты
  `services/api`; генерация: `python -m scripts.export_openapi`, CI: `--check`.
- `data-gate-*.schema.json` — отчёт импорта и manifest опубликованного снимка.

HTTP-ответ V1 расширяет доменный результат полями `versions` и `aqolScore` (алиас
`score`, не отдельная формула). `versions` в запросе необязателен для простого demo,
но интеграционный клиент должен отправлять объект из `/catalog`; несовпадение → 409.
Каждая selection обязательно содержит `measureId` и `districtId` (`null` для city).

## Согласование фронтенда

Фронтенд из `main@8f5103d` включён в ветку. HTTP normalizer адаптирован к каноническим
maps/decomposition движка, сохранена совместимость legacy/mock-ответов.
Три Node-теста проверяют преобразование и отправку версий; Compose использует `/api`.
Статические TypeScript declarations старого контракта пока отличаются от HTTP wire format:

| Поле | Канонический backend | Что согласовать в UI |
|---|---|---|
| Байконур | `baikonur` | Не `baykonur` |
| Экология | `environment` | Не `ecology` |
| `districtScores` | объект `{districtId: number}` | Не массив строк |
| `indicators`, `indicatorDeltas` | вложенные объекты район → показатель → число | Не массив `before/after/delta` |
| `decomposition` | каждый вклад имеет `{before, after, delta}` | Не `decomposition.delta.*` |
| Каталог показателей | `code`, `name`, `direction`, `scale`; веса в `weights` | Явно адаптировать `code` → UI `id` |
| Альтернативы | `{results: [{selections, evaluation, replacements}], ...}` | Использовать тот же evaluator presenter |

Различия преобразуются в `apps/web/src/infrastructure/httpV1Api.ts` без изменения формулы.
Проверка: из `apps/web` выполните `node --test src/infrastructure/httpV1Api.test.mjs`
после `npm ci`. Полная UX-приёмка и генерация единого TypeScript-клиента остаются отдельно.

## V2: отдельный backend-контракт

Пошаговое подключение фронтенда, точные маршруты, заголовки, команды, worker polling,
SSE reconnect и синтетические ограничения: [V2 API guide](../../docs/V2-API.md).
Существующие TypeScript declarations V1 не являются типами V2.

| Схема | Проверяет |
|---|---|
| `v2-dataset.schema.json` | Составной синтетический снимок города до публикации Data Gate |
| `v2-scenario.schema.json` | Ответ создания immutable Scenario; `$defs/createRequest` — вход |
| `v2-run.schema.json` | Публичный Run; `$defs/createRequest` — вход создания |
| `v2-run-manifest.schema.json` | Версии, хеши, seed, RNG, время и происхождение ветки |
| `v2-command.schema.json` | Команда; `$defs/accepted` — подтверждение, не завершение worker job |
| `v2-event.schema.json` | Полный объект журнала/SSE; trace возвращает внутренние события без HTTP-полей |
| `v2-checkpoint.schema.json` | Публичные метаданные checkpoint; `$defs/branchRequest` — запрос ветки/replay |
| `v2-evidence.schema.json` | Проверяемое значение метрики в конкретном прогоне |
| `v2-metrics.schema.json` | Ответ metrics; `$defs/metricSeries` — отдельная серия |

JSON Schema — Draft 2020-12. Межфайловые ссылки используют `urn:akim:v2:*`: валидатор
должен зарегистрировать локальные схемы по `$id`, сетевое скачивание не требуется.
`tests/v2/test_contracts.py` проверяет реальные ответы контроллера и проекции метрик.
Ограничения тела запросов авторитетно задаются Pydantic/OpenAPI; бизнес-проверки
команд (ресурсы, бюджет, версия состояния) выполняются сервером, не JSON Schema.
OpenAPI генерируется из текущего приложения и содержит маршруты обоих режимов.
