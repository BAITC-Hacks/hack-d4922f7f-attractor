# V2 API: контракт для фронтенда

V1 остаётся самостоятельным режимом с официальным Score. V2 — синтетическая
исследовательская модель `mode: dynamic-v2`, не прогноз реальной Астаны.
Этот документ описывает **реализованный HTTP API**, а не все будущие обещания ТЗ.
Интерфейс V2 в эту backend-поставку не входит.

## Подключение и права

Прямой base URL: `http://localhost:8000`; через существующий web reverse proxy:
`http://localhost:8080/api`. Например, `/v2/catalog` и `/api/v2/catalog` обращаются
к одному backend. Запуск стека и переменные окружения — в [README](../README.md).
Документация HTTP: `/docs`, машинный контракт: `/openapi.json`.

Локальный demo без `AKIM_RUN_TOKEN` допускает управление без авторизации. Если
токен задан, POST создания сценария, прогона, команд, checkpoint, ветки, replay,
эксперимента и его отмены требуют `Authorization: Bearer <AKIM_RUN_TOKEN>`.
Права импорта/публикации Data Gate проверяются отдельно через `AKIM_ADMIN_TOKEN`.
Чтение результатов публично; это не многопользовательская production-авторизация.
Не помещайте административные токены в собираемый публичный JS.

## Маршруты

| Метод и путь | Назначение | Результат |
|---|---|---|
| `GET /v2/catalog` | Снимок, районы, версии, параметры, статусы модулей | `dataSnapshotId`, `dataManifest`, `districts`, `modules`, `parameters`, `limitations` |
| `GET /v2/health` | Наличие worker | `status`, `worker`, `heartbeatAgeSeconds`; при остановке worker HTTP остаётся доступен |
| `POST /scenarios` | Создать immutable сценарий | 201, Scenario; одинаковая конфигурация даёт тот же `id` |
| `POST /runs` | Создать прогон, заголовок `Idempotency-Key` обязателен | 202, Run; изначально `status: paused` |
| `GET /runs/{runId}` | Состояние, manifest, версии и checkpoint | Run; события и метрики читаются отдельно |
| `POST /runs/{runId}/commands` | Команда, заголовок `Idempotency-Key` обязателен | 202, подтверждение; шаг исполняет worker |
| `POST /runs/{runId}/checkpoints` | Сохранить текущее состояние | 201, Checkpoint; во время незавершённого шага → 409 |
| `POST /runs/{runId}/branches` | Ветка из checkpoint, заголовок `Idempotency-Key` обязателен | 201, новый Run, paused |
| `POST /runs/{runId}/replay` | Воспроизвести историю от checkpoint | `matches`, `replayedHash`, `currentHash`, `checkpointId` |
| `GET /runs/{runId}/events` | SSE, по умолчанию поток | Именованные события `city-event`, `id = seq` |
| `GET /runs/{runId}/events?stream=false&after=0` | Порция журнала | `{events, nextSeq}`, максимум 1000 событий за чтение |
| `GET /runs/{runId}/metrics` | Серии и проверяемые основания | `{series, evidence}` |
| `GET /runs/{runId}/trace/{eventId}` | Причинная трасса через `causedBy` | `{events, limitation}`; до 500 связанных событий |
| `GET /runs/{runId}/agents/{agentId}/experience` | Опыт представителя населения | `{runId, agent, events}` |
| `GET /runs/{runId}/population` | Демография | `cohorts`, `migrationFlows`, `districts`, `status`, `unit` |
| `GET /runs/{runId}/development` | Застройка | `parcels`, `projects`, `housingStock` |
| `GET /runs/{runId}/flows` | Деньги | `transfers`, `ledger`, `accounts`, `basePeriod` |
| `GET /runs/{runId}/politics` | Синтетические институты | `politics`, `status`, `limitation` |
| `POST /experiments` | Поставить парный ансамбль в очередь, `Idempotency-Key` обязателен | 202, Experiment |
| `GET /experiments/{experimentId}` | Прогресс и результат ансамбля | `queued/running/completed/failed/cancelled`, `pairs`, `summary` |
| `POST /experiments/{experimentId}/cancel` | Прервать ансамбль между рабочими пакетами | Experiment |
| `POST /assistant/messages` | Детерминированная сводка по результатам | `mode: rule-based`, `claims`, `evidence`, `limitations`, `proposals: []` |
| `GET /runs/{runId}/export` | Переносимый результат | ZIP: `manifest.json`, `run.json`, `scenario.json`, `metrics.json` |

## Минимальный сценарий: снегопад

Запросы ниже — JSON, `Content-Type: application/json`. Идентификаторы из ответов
нужно подставить в следующие запросы, а не копировать примеры буквально.

1. `GET /v2/catalog`: сохранить `dataSnapshotId`, показать синтетический статус.
2. `POST /scenarios`:

```json
{"name":"Снегопад: проверка решения","mode":"dynamic-v2","weatherScenarioId":"snow","timeMode":"operational"}
```

Отсутствующий `dataSnapshotId` означает опубликованный demo-снимок каталога.
Сценарий фиксирует данные и параметры; обновление Data Gate не меняет его прошлое.
`economyScenarioId` пока только `synthetic-baseline`.

3. `POST /runs`, заголовок `Idempotency-Key: demo-create-1`:

```json
{"scenarioId":"<scenario.id>","seed":42,"horizon":720}
```

`horizon` — полное модельное время в минутах от начала, а не время CPU.
Оперативный режим ограничен 10 080 минутами (7 дней), стратегический — 5 184 000
минутами (120 условных месяцев по 30 дней). Начальное состояние — paused.

4. `POST /runs/{runId}/commands`, заголовок `Idempotency-Key: demo-step-1`:

```json
{"commandId":"step-1","idempotencyKey":"demo-step-1","expectedStateVersion":0,"type":"clock.step","payload":{"minutes":120},"issuedBy":"local-user"}
```

Сохранить ответ, затем опрашивать `GET /runs/{runId}` примерно раз в 500–1000 мс
до `pendingCommand: false`. `status: paused` **не означает**, что шаг закончен.
Если worker отсутствует, команда останется pending; проверить `/v2/health`.
Остановить polling при `failed/cancelled`; показать `error`, если он присутствует.

5. `POST /runs/{runId}/checkpoints` без тела. Сохранить `checkpoint.id`.
6. Дважды вызвать `POST /runs/{runId}/branches` с разными `Idempotency-Key`:

```json
{"checkpointId":"<checkpoint.id>"}
```

Ветки получают общее прошлое и парные RNG-потоки. В одной ветке оставить исходную
политику, в другой найти доступную бригаду в `state.crews`, например не из Нуры,
и отправить команду `crew.reassign` с её **фактическим** `crewId`.

```json
{"commandId":"crew-1","idempotencyKey":"demo-crew-1","expectedStateVersion":0,"type":"crew.reassign","payload":{"crewId":"<state.crews[].id>","districtId":"nura","durationMinutes":360},"issuedBy":"local-user"}
```

Продвинуть обе ветки на одинаковое время; сравнивать одинаковые метрики, единицы,
окна и группы. У решения есть стоимость: улучшение не обещается бесплатным.
Для каждого нового действия читать актуальную **верхнеуровневую** `stateVersion`
из Run, а не одноимённое поле вложенного доменного `state`.

## Команды, версии и повторная отправка

`Idempotency-Key` в заголовке команды обязан совпадать с `idempotencyKey` в теле.
Повтор после сетевого сбоя отправляется с **тем же ключом и тем же телом**:
возвращается исходное подтверждение, бюджет повторно не списывается.
Тот же ключ с другим телом → `409 idempotency_conflict`.
Устаревшая `expectedStateVersion` → `409 state_version_conflict`: перечитать Run,
обновить намерение пользователя и отправить новую команду с новым ключом.
Не делайте автоматический бесконечный retry управленческих решений.

| `type` | `payload` | Поведение |
|---|---|---|
| `clock.step` | `{"minutes":120}` | Точный ограниченный шаг, не выходящий за горизонт |
| `clock.resume` | `{}` | Продолжить непрерывный прогон или приостановленный шаг |
| `clock.pause` | `{}` | Остановиться между ограниченными пакетами; pending-шаг сохраняется |
| `clock.speed` | `{"speed":60}` | 1–43 200 модельных минут за запрошенный пакет, не FPS и не обещанный realtime multiplier |
| `clock.cancel` | `{}` | Терминальное состояние cancelled |
| `crew.reassign` | `crewId`, `districtId`, необязательно `durationMinutes`, `startMinute` | Переброска доступной бригады; будущий старт резервирует деньги |
| `project.start` | `districtId`, `projectType: school/road`, `capex`, `opexMonthly`, `capacity`, `durationMonths`; школе ещё `parcelId` | Проект с CAPEX, сроком и OPEX; школа требует свободный social-участок |
| `development.moratorium` | `districtId`, `reason`, необязательно `durationMinutes` | Мораторий с публичной причиной |
| `developer.requirement` | `districtId`, `schoolPlacesPerUnit` (0–3) | Условия для новых строек |
| `land.allocate` | `parcelId`, `use: school/housing` | Выделение совместимого участка |
| `hearing.schedule` | `subjectId` или `parcelId`, необязательно `delayMinutes` | Синтетическое слушание в модельном времени |
| `zoning.change` | `parcelId`, `zone: residential/social/protected`, необязательно `maxUnits`, `districtId` | После слушания; голосование может отклонить изменение |
| `budget.submit`, `budget.amend` | `amount`, необязательно `districtId` | Синтетическое голосование; заём не включён |
| `promise.announce` | `metricId`, `target`, `deadlineMinute`, `direction: at-most/at-least`, необязательно `districtId` | Проверяемое обещание по уже существующей метрике |

`accepted: true` — принятие команды системой, **не** обещание положительного
голосования или завершения проекта. Смотрите журнал `vote.passed/vote.failed`,
состояние проекта и ledger. Неизвестные команды отвергаются, не имитируются.
Дата будущего старта поддерживается сейчас только у `crew.reassign`.

## SSE и причинные основания

```javascript
const source = new EventSource(`${base}/runs/${runId}/events?after=${lastSeq}`);
source.addEventListener('city-event', (message) => {
  const event = JSON.parse(message.data);
  // Хранить курсор отдельно для каждого runId; обрабатывать события по seq.
  lastSeq = event.seq;
  renderEvent(event);
});
// При смене прогона или размонтировании компонента:
// source.close();
```

Стандартный EventSource сам передаёт `Last-Event-ID` при reconnect; для нового
соединения передайте сохранённый курсор `after`. Backend выбирает максимальный из
двух курсоров и отдаёт события строго после него. `seq` и `event.id` имеют смысл
внутри конкретного `runId`: идентификаторы событий разных веток могут совпадать.
Пустой поток шлёт keepalive; SSE не является потоком полных состояний города.
`simTime` — модельное время. `recordedAt` — время записи рабочего пакета событий,
не независимое наблюдение физического события.

В `/metrics` каждая точка ссылается на `evidenceId`; соответствующая запись
содержит `runId`, `metric`, `value`, `unit`, `window`, `districtId`, `sourceIds`.
Для причинной трассы используйте `sourceIds` событий и `/trace/{eventId}`.
Пустой `sourceIds` не нужно заменять выдуманным основанием. Окно метрики берётся
из ответа; `aggregation: model-output` не означает автоматически среднее или p90
по всем жителям. Семантика конкретного показателя определяется версией модели.
`null` в значении — неизвестное, не ноль.

## Парный эксперимент и сводка без ключа AI

`POST /experiments`, заголовок `Idempotency-Key: snow-ensemble-1`:

```json
{"scenarioId":"<scenario.id>","seeds":[11,22,33],"warmup":120,"horizon":720,"intervention":{"type":"crew.reassign","payload":{"crewId":"<valid crew id>","districtId":"nura","durationMinutes":360}}}
```

Seed должны быть уникальными, от 2 до 30; `warmup < horizon`. Worker исполняет
пары «без решения / с решением» из одного прошлого. Опросить
`GET /experiments/{experimentId}` до терминального статуса. `summary[metric]`
содержит `median`, `p05`, `p95`, `min`, `max`, `n`, `unit`. Это распределение
**парной разницы intervention − baseline**, не абсолютные метрики и не
доверительный интервал среднего. Малый demo-ансамбль не доказывает устойчивость.
`budgetViolationRate` — доля пар с нарушением финансового ограничения.

`POST /assistant/messages`:

```json
{"runId":"<runId>","message":"Покажи последствия решения и основания"}
```

V2 отвечает без LLM/API-ключа: `mode: rule-based`, расчётные `claims` и `evidence`.
Текст сообщения не превращается в команду и не меняет состояние. В V2 пока нет
NPC-диалога или LLM-планировщика; не выдавайте шаблонную сводку за генеративного агента.

## Границы интерфейса

- Показывать `modules` из каталога: `not-implemented` нельзя оформлять как работающую функцию.
- Районы брать из каталога; не зашивать пять районов V1. Demo V2 содержит шесть.
- Часы strategic используют условные 30-дневные месяцы; не подписывать их как календарный прогноз.
- Все финансовые значения demo — KZT базового периода 2026-01; это не условные единицы V1.
- Сохранять manifest при экспорте/сравнении; `codeRevision` желательно задавать SHA сборки.
- Не складывать V2-метрики с V1 Score. Синтетические политические группы — гипотезы модели, не реальное голосование жителей.
- Результат backend готов для подключения фронтенда; существующий V1 frontend не переделан в V2 автоматически.
