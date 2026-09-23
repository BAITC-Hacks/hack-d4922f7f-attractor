# V2 frontend architecture: «Живой город»

Статус: архитектурное решение для frontend V2.  
Дата: 23 сентября 2026 года.  
Источники истины:

- `origin/main@2120d0b`: фактический исполняемый код;
- `origin/docs/v2-spec@47bb6f4:docs/09-v2-technical-spec.md`: требования V2;
- `origin/docs/v2-spec@47bb6f4:docs/10-frontend-plan.md`: frontend-план;
- `docs/02-architecture.md`, `docs/04-v2-simulation.md`: базовые сущности и модель времени.

При расхождении документа и кода текущий код определяет статус «реализовано», а V2-ТЗ —
целевой контракт. Этот документ не объявляет запланированные возможности готовыми.

## 1. Фактическое состояние

На свежем `origin/main` доступны:

- React 19 + TypeScript + Vite, MapLibre GL;
- offline fixtures V1 и HTTP adapter;
- `GET /health`, `GET /catalog`, `POST /v1/validate`, `POST /v1/evaluate`;
- детерминированный V1 engine и Data Gate;
- карта районов, выбор показателя, точки мер, 3D-здания из внешней подложки;
- контрольные значения V1 `52.55768 → 56.54307`.

Не реализованы:

- `engine/v2`, scheduler, глобальные модельные часы, worker и checkpoints;
- Scenario/Run/Command/Event/Metric HTTP-контракты V2;
- SSE, replay, ветвление и ансамбли;
- `POST /v1/analysis` и весь AI runtime;
- Data Gate HTTP routes;
- `POST /v1/alternatives`: типы, frontend port и fixture существуют, но route в
  `api/main.py` отсутствует;
- bootstrap текущего состояния V2 run: в ТЗ есть `POST /runs`, events и metrics, но нет
  endpoint, который отдаёт согласованный снимок для первого открытия и восстановления UI.

Спецификация `origin/docs/v2-spec` создана до последних merge: её утверждения «HTTP API нет»
и «frontend только в отдельной ветке» устарели. Утверждение «динамический V2 не реализован»
подтверждается деревом свежего `origin/main`.

Текущий GeoJSON содержит пять районов V1 и Сарайшык с `in_v1_model: false`. ID Байконура
расходится: UI/GeoJSON используют `baykonur`, engine — `baikonur`; текущий API скрывает это
alias-адаптером. Для V2 каноническим становится ID из опубликованного Data Gate snapshot;
старое значение нормализует infrastructure adapter, а не presentation.

## 2. Переключение V1/V2 по capabilities и версиям

V1 и V2 — разные режимы продукта, а не два вида одного Score:

- `official-v1`: неизменяемый снимок, ровно пять мер, один детерминированный результат;
- `dynamic-v2`: состояние во времени, команды, события, ledger, seed, ветки и эксперименты;
- V2 не пересчитывает и не изменяет официальный V1 Score;
- модельный адаптер V2 к T1…C2, если появится, получает отдельную версию и подпись
  «модельный индекс», а не AQoL V1.

Frontend не определяет готовность V2 по наличию кнопки или environment variable. Backend
должен сообщать capability и версии. До появления такого endpoint V2 отображается только
как `planned`, без попыток вызвать отсутствующие routes.

```ts
type CapabilityStatus = "available" | "planned" | "disabled";

type VersionStamp =
  | {
      contractVersion: "1";
      mode: "official-v1";
      catalogVersion: string;
      dataSnapshotId: string;
      modelVersion: string;
      rulesVersion: string;
    }
  | {
      contractVersion: "1";
      mode: "dynamic-v2";
      dataSnapshotId: string;
      modelVersion: string;
      rulesVersion: string;
      parameterSetId: string;
      runtimeVersion: string;
      rngVersion: string;
      codeRevision: string;
    };

interface ProductCapabilities {
  modes: Array<{
    mode: VersionStamp["mode"];
    status: CapabilityStatus;
    versions?: VersionStamp;
    missingRequirements?: string[];
  }>;
}
```

`GET /capabilities` — необходимый, но отсутствующий backend endpoint. Допустимая первая
реализация — расширить `GET /catalog` полем `capabilities`; отдельный endpoint предпочтительнее,
потому что V2 не является каталогом V1. Переключатель режима активен только при
`status: available`. Смена режима очищает selection/run projection и использует другой cache
namespace.

Версии постоянно видимы в UI. Для V2 дополнительно показываются `runId`, `seed`,
`parameterSetId`, `runtimeVersion`, `rngVersion` и `codeRevision`. Любой экспорт сохраняет
полный `VersionStamp`.

## 3. Clean Architecture frontend

```text
apps/web/src/
├── domain/
│   ├── shared/       VersionStamp, ValueWithProvenance, DataQuality
│   ├── v1/           Selection, Evaluation, официальный AQoL
│   └── v2/           Scenario, Run, RunEvent, MetricSeries, MapLayerState
├── application/
│   ├── ports/        ProductBootstrap, V1Api, RunsApi, EventStream, MapRenderer
│   └── use-cases/    bootstrapProduct, evaluateV1, openRun, controlRun,
│                     reconnectRun, compareBranches
├── infrastructure/
│   ├── http/         capabilities, V1, runs, metrics, experiments
│   ├── sse/          Last-Event-ID, backoff, gap recovery
│   ├── cache/        memory query cache + IndexedDB versioned assets
│   ├── fixtures/     explicit V1/V2-demo adapters
│   └── map/          MapLibre adapter + neutral-scheme adapter
└── presentation/
    ├── shell/        mode switch, versions, connectivity, data maturity
    ├── v1/           city, decisions, result
    └── v2/           live city, run controls, district, event trace, lab
```

Правило зависимостей:

```text
presentation → application → domain
infrastructure ─implements→ application ports
domain imports: no React, fetch, EventSource, MapLibre, IndexedDB
```

Нужны только реальные seams:

- `V1Api`: HTTP adapter и fixture adapter;
- `RunsApi`: будущий HTTP adapter и V2 fixture/replay adapter;
- `EventStream`: SSE adapter и fixture event-player adapter;
- `MapRenderer`: MapLibre adapter и нейтральная схема без сети;
- `AssetCache`: IndexedDB и memory adapter для тестов.

Не создаются отдельные repository/use-case для каждого `GET`. Глубокий модуль `RunSession`
скрывает bootstrap, применение событий, gap detection, reconnect, команды и 409 recovery:

```ts
interface RunSession {
  open(runId: string, signal?: AbortSignal): Promise<RunProjection>;
  subscribe(listener: (state: RunProjection) => void): () => void;
  command(command: RunCommand, signal?: AbortSignal): Promise<void>;
  close(): void;
}
```

Presentation не меняет авторитетные бюджет, очередь, метрики или карту самостоятельно.
Оптимистично показывается только состояние команды `pending`; подтверждённое состояние
приходит из bootstrap/журнала.

## 4. API-контракты frontend V2

### 4.1 Матрица routes

| Route | Статус | Назначение frontend |
|---|---|---|
| `GET /catalog` | доступен | V1 catalog и версии |
| `POST /v1/validate` | доступен | авторитетная проверка V1 |
| `POST /v1/evaluate` | доступен | авторитетный результат V1 |
| `POST /v1/alternatives` | **нет backend route** | проверенные альтернативы V1 |
| `GET /capabilities` | **нет в ТЗ и backend** | безопасный V1/V2 switch |
| `POST /scenarios` | **только ТЗ** | immutable Scenario |
| `POST /runs` | **только ТЗ** | создать асинхронный run |
| `GET /runs/{id}/state` | **пробел ТЗ/backend** | bootstrap/recovery snapshot |
| `POST /runs/{id}/commands` | **только ТЗ** | pause/step/speed/решение акима |
| `POST /runs/{id}/branches` | **только ТЗ** | ветка из checkpoint |
| `GET /runs/{id}/events` | **только ТЗ** | SSE journal + агрегаты |
| `GET /runs/{id}/metrics` | **только ТЗ** | MetricSeries + Evidence |
| `POST /experiments` | **только ТЗ** | ансамбль прогонов |
| `POST /assistant/messages` | **только ТЗ** | AI-ответ с evidence |
| `GET /runs/{id}/export` | **только ТЗ** | manifest, результат, журнал |

### 4.2 Bootstrap

`POST /runs` по ТЗ возвращает только `{runId, status}`; этого недостаточно для UI. Добавляется
`GET /runs/{id}/state` с согласованным снимком. Endpoint помечен как обязательный пробел,
пока backend его не реализует.

```ts
interface RunBootstrap {
  manifest: RunManifest;
  run: {
    runId: string;
    scenarioId: string;
    status: "created" | "running" | "paused" | "completed" | "failed" | "cancelled";
    stateVersion: string;
    simTime: string;
    lastEventSeq: number;
  };
  modules: Array<{
    id: string;
    status: "available" | "not-implemented" | "degraded";
    dataStatus: "observed" | "estimated" | "synthetic";
    assumptions: string[];
    missingData: string[];
  }>;
  ledger: {
    currency: string;
    priceBasePeriod: string;
    cash: number | null;
    reserved: number | null;
    availableToCommit: number | null;
  };
  metrics: MetricSeries[];
  map: MapManifest;
}
```

Снимок возвращается с `Cache-Control: no-store`. `lastEventSeq` задаёт точку подключения
SSE: после bootstrap клиент просит события строго после неё.

### 4.3 Команды, идемпотентность и 409

```ts
interface RunCommand {
  commandId: string;
  idempotencyKey: string;
  expectedStateVersion: string;
  type:
    | "clock.pause" | "clock.resume" | "clock.step" | "clock.speed"
    | "crew.reassign" | "project.start" | "funding.change"
    | "service.policy" | "transport.service";
  payload: unknown;
  issuedBy: string;
}
```

`POST /runs` и `POST /runs/{id}/commands` получают header `Idempotency-Key`. Для команды
значение header совпадает с `body.idempotencyKey`; несовпадение — `400 invalid_request`.
Повтор возвращает прежний результат и не создаёт вторую ledger entry.

Успех:

```json
{"commandId":"cmd-42","accepted":true,"stateVersion":"sv-108"}
```

Конфликт:

```http
HTTP/1.1 409 Conflict
Content-Type: application/json

{"code":"state_version_conflict","field":"expectedStateVersion","message":"Состояние прогона изменилось; загрузите актуальный снимок"}
```

На `409` frontend не повторяет изменяющую команду автоматически: очищает optimistic pending,
вызывает `GET /runs/{id}/state`, показывает diff/сообщение и оставляет повтор пользователю.
Timeout безопасно повторяется только с тем же `Idempotency-Key`.

### 4.4 SSE, reconnect и backpressure

Базовый event соответствует V2-ТЗ:

```ts
interface CityEvent {
  id: string;
  runId: string;
  seq: number;
  simTime: string;
  recordedAt: string;
  type: string;
  actorId: string | null;
  districtId: string | null;
  causedBy: string[];
  payloadSchemaVersion: string;
  payload: unknown;
}
```

Правила потока:

1. SSE `id` равен строковому `seq`.
2. Клиент подключается с `Last-Event-ID: <lastAppliedSeq>`.
3. `seq <= lastAppliedSeq` игнорируется как повтор.
4. `seq > lastAppliedSeq + 1` означает gap: проекция замораживается, соединение
   переподключается с последнего применённого `seq`.
5. Если журнал уже compacted или сервер отвечает `410`, выполняется новый bootstrap.
6. Backoff: `1s → 2s → 4s → 8s`, максимум 15s, с jitter; успешное событие сбрасывает backoff.
7. События применяются по `seq`, не по `recordedAt`.
8. UI рендерит агрегаты 1–2 раза/с; journal buffer не теряет события. Массовые NPC не
   рисуются по одному.

ТЗ не определяет DTO агрегата в SSE. До его фиксации frontend принимает только `CityEvent`;
агрегаты получает из `/metrics`. Если backend добавит stream item `aggregate`, для него
нужна отдельная JSON Schema с `stateVersion`, окном и единицами.

## 5. State, Event и Run model

V1 state — результат чистого вызова для immutable snapshot. V2 state — server-authoritative
проекция журнала:

```ts
interface RunProjection {
  versions: Extract<VersionStamp, {mode: "dynamic-v2"}>;
  runId: string;
  scenarioId: string;
  status: "created" | "running" | "paused" | "completed" | "failed" | "cancelled";
  stateVersion: string;
  simTime: string;
  lastAppliedSeq: number;
  connection: "connecting" | "live" | "reconnecting" | "offline" | "failed";
  pendingCommandIds: string[];
  modules: Record<string, "available" | "not-implemented" | "degraded">;
  ledger: RunBootstrap["ledger"];
  metrics: Record<string, MetricSeries>;
  map: MapProjection;
}
```

Инварианты:

- `Scenario` immutable; изменение создаёт новый scenario/branch;
- Run проходит `created → running ⇄ paused → completed`, либо `failed/cancelled`;
- frontend не является event store и не гарантирует replay;
- один event применяется максимум один раз по `(runId, seq)`;
- `simTime` — модельное время, `recordedAt` — время записи; UI не смешивает их;
- физическая динамика не зависит от текста LLM;
- `Y(t)` — рассчитанные метрики, `O(t)` — наблюдения; обращения относятся к `O(t)`;
- ветка имеет общее прошлое до checkpoint и отдельное будущее;
- неизвестное значение — `null`, не `0`;
- все числовые значения несут единицу.

Локальный reducer принимает только нормализованные действия:

```text
BOOTSTRAP_LOADED → EVENT_APPLIED → METRICS_REFRESHED
COMMAND_PENDING → COMMAND_ACCEPTED | COMMAND_REJECTED | VERSION_CONFLICT
STREAM_LOST → STREAM_RESTORED | RESYNC_REQUIRED
```

## 6. Time charts, projections, provenance и confidence

Frontend не строит прогнозы и не интерполирует отсутствующие точки. Он визуализирует
`MetricSeries`, Evidence и результаты эксперимента с сервера.

```ts
interface MetricPoint {
  time: string;
  value: number | null;
  lower?: number | null;
  upper?: number | null;
}

interface MetricSeries {
  metricId: string;
  label: string;
  unit: string;
  window: [string, string];
  aggregation: string;
  groupBy: Record<string, string>;
  points: MetricPoint[];
  evidenceIds: string[];
  provenance: "observed" | "simulated" | "assumed" | "derived";
  uncertainty?: {
    kind: "outcome_interval" | "mean_estimate_interval" | "parameter_range";
    level: number | null;
    method: string;
    runCount: number | null;
  };
}
```

Правила визуализации:

- observed — сплошная линия; simulated — штриховая; assumed — пунктир/amber;
  derived — линия с бейджем «расчёт»;
- prediction/forecast всегда имеет отдельный фон после границы `now/simTime`;
- `null` создаёт разрыв линии и подпись «нет данных», не точку на нуле;
- единица, aggregation, окно и group видимы рядом с графиком;
- одиночный seed подписан «один прогон» и не показывается как прогноз;
- эксперимент показывает медиану, интервал, хвостовой риск и долю нарушения ограничений;
- outcome interval и interval оценки среднего получают разные подписи;
- `confidence` не вычисляется на клиенте и не заменяется декоративным процентом;
- кликом по точке открываются Evidence и причинная трасса по `causedBy`;
- график позволяет выбрать operational, daily или strategic scale, но не смешивает
  поток и запас в одной серии без явной агрегации.

## 7. Матрица слоёв карты

| Слой | Статус | Источник | Время | Отображение и ограничения |
|---|---|---|---|---|
| Подложка | доступна V1, зависит от сети | OpenFreeMap `bright` | статично | при отказе — нейтральная схема; аналитический сценарий должен остаться доступен |
| Границы районов | доступен fixture | `astana-districts.geojson`, публичная ArcGIS-геометрия | версия snapshot | 5 районов V1; Сарайшык серый `вне модели V1`; до проверки подписывать «схема» |
| Районный показатель / choropleth | доступен V1 | baseline `GET /catalog`, after из `/v1/evaluate` | V1 before/after | шкала 0–100 с единицей; критическое `<40`; V2 получает только из MetricSeries |
| Районный AQoL delta | доступен V1 после evaluate | `/v1/evaluate.districtScores` | before/after | дивергентная шкала и текстовая таблица как accessibility fallback |
| Меры портфеля | доступен V1 | selections + условные центроиды районов | сценарий V1 | это опорные точки, не реальные координаты проектов |
| 3D-здания | доступен визуально при zoom ≥15 | building source OpenFreeMap, `render_height` fallback 8 | статично | иллюстративный слой; не источник официальных метрик |
| Транспортная сеть | **не реализована** | V2 `transport-network-v1` Data Gate snapshot | snapshot | RoadEdge/Route; текущий toggle disabled |
| Загрузка дорог и маршрутов | **не реализована** | transport metrics/events | operational 5–15 мин | width/color по v/c, travel time и unmet demand; агрегаты, не отдельные поездки |
| Перекрытия и снег | **не реализован** | weather scenario + caused events | operational | окно события и коэффициент мощности; без второго независимого «штрафа за снег» |
| Служебные активы ЖКХ | **не реализованы** | `services-v1`, UtilityAsset | operational/daily | состояние, недоступность и provenance |
| Бригады и задания | **не реализованы** | Crew, service queue, CityEvent | operational | кластер/агрегат; выбранная бригада — детально; не рисовать все перемещения |
| Школы и поликлиники | **не реализованы** | `facilities-v1`, Facility metrics | daily | мощность, staff/funded capacity, очередь и доступность |
| Зелёные зоны | **не реализованы** | `environment-v1`, GreenArea/Tree | daily/strategic | наблюдаемая и synthetic geometry различаются бейджем; не выводить AQI из числа деревьев |
| Безопасность / инциденты | **не реализованы** | safety events и exposure metrics | operational | фактические и зарегистрированные события — разные слои |
| Обращения | **не реализованы** | Appeal / `O(t)` | operational/daily | heat/cluster по территории; количество обращений не равно количеству проблем |
| Проекты акима | **не реализованы** | Project + accepted command | strategic | этап, CAPEX/OPEX, срок и статус; pending не смешивается с accepted |
| Финансовые обязательства | **не геослой по умолчанию** | ledger metrics | strategic | появляются на карте только при наличии district/object reference |
| Плотность жителей/спроса | **не реализована** | weighted Resident/Household aggregates | daily | только агрегаты и coverage; не анимировать тысячи NPC |
| Branch delta | **не реализован** | два run из checkpoint + compare result | выбранное окно | baseline/intervention, одна легенда и один metricId |
| Качество/происхождение данных | **не реализовано** | Data Gate report + Evidence | версия snapshot | overlay missing/estimated/observed; `null` не окрашивать как ноль |

Каждый слой получает `layerId`, `dataVersion`, `sourceStatus`, `unit`, `timeWindow`,
`updatedAt`, `coverage`, `legend`. Нереализованный слой показывается disabled с причиной,
но не питается выдуманной лентой.

## 8. Cache и version invalidation

Кеш разделён на immutable assets и mutable run projection.

| Данные | Хранилище | Ключ | Инвалидация |
|---|---|---|---|
| capabilities | memory | deployment/API origin | короткий TTL; hard refresh |
| V1 catalog | IndexedDB + memory | `v1:{catalogVersion}:{dataSnapshotId}:{rulesVersion}` | новая версия или ETag |
| geometry/static assets | IndexedDB | `{assetId}:{snapshotId}:{checksum}` | новый manifest/checksum |
| Scenario | memory/IndexedDB | `{scenarioId}:{versions}` | immutable, не перезаписывается |
| Run bootstrap | memory | `{runId}:{stateVersion}` | любое принятое событие/команда |
| MetricSeries history | query cache | `{runId}:{metricId}:{window}:{aggregation}:{groupBy}` | закрытое окно сохраняется; текущее окно обновляется |
| SSE cursor | session storage | `{runId}:lastEventSeq` | bootstrap с меньшим/несовместимым журналом |
| offline fixtures | отдельный namespace | `fixture:{fixtureVersion}` | новая fixture version |

Backend пока не выставляет ETag для `/catalog`; это отмечено как недостающая оптимизация, а
не существующая гарантия. До ETag frontend сравнивает версии тела ответа.

Правила:

- смена `dataSnapshotId`, `modelVersion`, `rulesVersion` или `parameterSetId` запрещает
  смешивать результаты и очищает derived view models;
- смена `stateVersion` инвалидирует только актуальный run snapshot, не immutable history;
- schema/contract mismatch не «нормализуется» молча: режим блокируется как incompatible;
- fixture и live API никогда не объединяются в одной сессии; fixture имеет постоянный badge;
- SSE cursor сохраняется только для reconnect, но не заменяет server bootstrap;
- logout/смена прав очищает приватный run cache.

## 9. Поэтапный MVP

| Фаза | Объём frontend | Backend-зависимость | Результат |
|---|---|---|---|
| F0 — contract gate | capabilities/version DTO, Run/Event/Metric schemas, canonical district IDs, fixture validation | OpenAPI/JSON Schema | один источник истины, V2 честно `planned` |
| F1 — V1 hardening | реальный catalog/validate/evaluate, ошибки у полей, AQoL/decomposition, схема без сети | существующий API; alternatives остаётся disabled | воспроизводимый обязательный сценарий V1 |
| F2 — V2 shell | mode switch, RunSession, clocks, module status, fixture EventStream, карта planned layers | V2 fixtures | UI и reconnect тестируются без заявления о live V2 |
| F3 — P3 integration | create/open run, bootstrap, pause/step/speed, SSE, 409 recovery, ledger summary | Scenario/Run/Command/Event/Metric endpoints | воспроизводимые часы и управление run |
| F4 — P4 snow slice | weather, transport/service layers, appeals, branch compare, причинная трасса | worker + checkpoint/branch + снегопад | полный сценарий «Снегопад» |
| F5 — P5/P6 lab | facilities/environment/safety/projects, experiments, intervals, AI/evidence, Data Gate UI | модули P5, experiments, assistant | исследовательская лаборатория без ложной точности |

Нельзя переносить в F3 декоративные NPC, полный 3D-город или чат вместо отсутствующих
Run/Event/Metric contracts. Первый live V2 срез — снег → мощность → задержка/очередь →
обращение → решение акима → ветка сравнения.

## 10. Acceptance tests

| ID | Проверка | Ожидаемый результат |
|---|---|---|
| CAP-01 | backend сообщает только V1 available | V2 виден как planned/disabled, V2 routes не вызываются |
| CAP-02 | версии режима меняются | cache namespace меняется, старые results не смешиваются |
| V1-01 | контрольный портфель | UI показывает `52.55768 → 56.54307` из API |
| V1-02 | invalid portfolio | `score:null`, ошибки привязаны к полям; карта не изображает результат как подтверждённый |
| BOOT-01 | открыть существующий run | bootstrap задаёт status, simTime, stateVersion, lastEventSeq, metrics и map manifest |
| SSE-01 | разрыв сети на 10 секунд | reconnect с Last-Event-ID; все seq применены ровно один раз |
| SSE-02 | duplicate event | state и ledger projection не меняются второй раз |
| SSE-03 | gap или `410` | UI замораживает projection и выполняет resync/bootstrap |
| CMD-01 | одна команда отправлена дважды с тем же key | один command result и одна ledger reservation |
| CMD-02 | `expectedStateVersion` устарел | `409`, автоматического destructive retry нет, загружен новый bootstrap |
| RUN-01 | pause/step/speed | pause подтверждена <1s; step двигает ровно заданное модельное время |
| RUN-02 | ветки без вмешательства из одного checkpoint | контрольные состояния совпадают; UI не смешивает события веток |
| MAP-01 | слой `not-implemented` | disabled с причиной, без fake events |
| MAP-02 | подложка недоступна | нейтральная схема и текстовая таблица сохраняют основной сценарий |
| MAP-03 | Сарайшык в V1 | серый и явно «вне модели V1» |
| DATA-01 | metric value равен `null` | «нет данных», разрыв графика, не ноль |
| DATA-02 | series имеет provenance | видимы status, unit, window, aggregation и evidence link |
| UNC-01 | результат одного seed | подпись «один прогон», без band/confidence claim |
| UNC-02 | ансамбль | медиана, тип интервала, метод, число прогонов и доля нарушений видимы |
| CACHE-01 | изменился snapshot/model/rules/parameters | несовместимые view models и assets инвалидированы |
| AI-01 | AI недоступен | run, бюджет, карта и метрики продолжают работать; rule-based fallback помечен |
| A11Y-01 | карта недоступна клавиатуре/сети | тот же смысл доступен в таблице; controls имеют labels и читаемый contrast |

Контрактные fixtures валидируются теми же JSON Schema/OpenAPI, что и live API. E2E не
считает наличие красивой карты доказательством динамической симуляции: обязательные
свидетельства V2 — журнал seq, версии, command result, checkpoint/branch и MetricSeries с
provenance.
