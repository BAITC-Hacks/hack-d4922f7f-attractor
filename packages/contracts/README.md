# Контракты

- `v1-*.schema.json` — исходные framework-independent запрос/ответ application layer.
  Формат существующих схем сохранён; их проверяют golden/HTTP tests.
- `openapi.json` — исполняемый HTTP-контракт версии `0.2.0`, включая схемы запросов,
  evaluate/validate/alternatives/analysis. Источник: Pydantic-модели и маршруты
  `services/api`; генерация: `python -m scripts.export_openapi`, CI: `--check`.
- `data-gate-*.schema.json` — отчёт импорта и manifest опубликованного снимка.

HTTP-ответ V1 расширяет доменный результат полями `versions` и `aqolScore` (алиас
`score`, не отдельная формула). `versions` в запросе необязателен для простого demo,
но интеграционный клиент должен отправлять объект из `/catalog`; несовпадение → 409.
Каждая selection обязательно содержит `measureId` и `districtId` (`null` для city).

## Согласование фронтенда

Проверялся черновой `origin/codex/aygerim-frontend`; он не менялся в backend-задаче.
Его TypeScript declarations/HTTP normalizer пока не совпадают с контрактом `main`.

| Поле | Канонический backend | Что согласовать в UI |
|---|---|---|
| Байконур | `baikonur` | Не `baykonur` |
| Экология | `environment` | Не `ecology` |
| `districtScores` | объект `{districtId: number}` | Не массив строк |
| `indicators`, `indicatorDeltas` | вложенные объекты район → показатель → число | Не массив `before/after/delta` |
| `decomposition` | каждый вклад имеет `{before, after, delta}` | Не `decomposition.delta.*` |
| Каталог показателей | `code`, `name`, `direction`, `scale`; веса в `weights` | Явно адаптировать `code` → UI `id` |
| Альтернативы | `{results: [{selections, evaluation, replacements}], ...}` | Использовать тот же evaluator presenter |

Это задача адаптера/генерации клиента, а не повод менять формулу V1. Перед merge
фронтенда нужен контрактный тест реального HTTP-клиента против API; текущий backend
suite не доказывает, что черновой фронтенд уже совместим.
