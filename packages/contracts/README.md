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
