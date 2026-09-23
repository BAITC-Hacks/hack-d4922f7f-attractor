# Frontend Track 12: Clean Architecture и динамическая карта Астаны

Дата: 23 сентября 2026 года  
Статус: **в работе**  
Ветка: `codex/aygerim-frontend`  
Время до feature freeze: менее 3 часов

## Решение

Собираем не GIS-платформу, а один убедительный вертикальный сценарий:

1. frontend запрашивает каталог городов и выбирает Астану;
2. получает версионированный пакет города и сохраняет его в IndexedDB;
3. показывает карту, dashboard, прогнозы и исходный `Baseline State`;
4. каждое действие пользователя мгновенно меняет локальный `City State` и карту;
5. backend подтверждает расчёт, а frontend принимает только ответ актуальной
   `state_revision`;
6. AI-совет запускается отдельно по уже рассчитанному `scenario_hash`.

Карта и dashboard — две проекции одного `City State`. Отдельного «состояния
карты» с собственными числами нет.

```text
catalog → city package/cache → Baseline State
                                │
user command → local reducer → City State revision N → map + dashboard
                                │
                                └→ debounced evaluate(N)
                                      │
                        response N? ───┴─── yes → reconcile
                              no → discard stale response
```

## 1. Что берём из предложенного картографического стека

| Компонент | Роль в MVP | Решение |
|---|---|---|
| MapLibre GL JS | basemap, районы, подписи, choropleth, 3D buildings | обязательный |
| deck.gl `MapboxOverlay` | сложные GPU-слои и редактируемые сценарные объекты | подключать после базовой карты |
| `@deck.gl-community/editable-layers` | `DrawPolygonMode`, `ModifyMode`, `TranslateMode` для парка/маршрута | один демонстрационный инструмент |
| Turf.js | площадь и длина созданной геометрии, spatial checks | только геометрические метрики |
| OSM/Overpass | источник одноразового snapshot | preprocessing, не runtime API |
| PMTiles | офлайн-подложка большого города | stretch goal после вертикали |

`deck.gl` не нужен для пяти районных полигонов: их дешевле и надёжнее рисует
MapLibre. Его ценность начинается с 3D, большого количества объектов и
редактирования. Если интеграция editable layer не поднялась за 20 минут, остаётся
MapLibre и сценарные объекты добавляются кликом по карте.

Не редактируем административные границы районов: показатели датасета привязаны к
фиксированным пяти районам. Пользователь создаёт только сценарные объекты:

- полигон нового парка;
- точку умного светофора;
- линию нового/изменённого маршрута.

Эти объекты преобразуются в доменные команды `AddPark`, `AddTrafficSignal`,
`AddTransitRoute`. Изменённый GeoJSON сам по себе не меняет официальный Score:
Score меняют только официальные меры и правила датасета.

## 2. Данные Астаны и воспроизводимость

Runtime не должен зависеть от Overpass или API-ключа. В репозиторий кладётся
малый проверенный snapshot:

```text
data/cities/astana/
├── manifest.json
├── districts-5-v1.geojson
├── pois-demo-v1.geojson
├── scenario-objects-empty.geojson
├── neutral-style.json
└── buildings-demo-v1.geojson       # optional, ограниченный объём
```

Полный bbox из примера `51.09,71.36,51.18,71.50` покрывает центральный demo-area,
а не гарантированно всю административную территорию Астаны. Поэтому файл и UI
должны честно называться `demo snapshot`. Полный городской слой зданий нельзя
обещать до проверки размера и производительности.

Для высоты здания применяется явная цепочка fallback:

```text
height → building:levels × 3 м → apartments: 30 м → остальные: 12 м
```

Каждый snapshot хранит `source`, `snapshot_date`, `license` и `attribution`.
Публичные OSM tiles нельзя массово скачивать для офлайн-режима; при отсутствии
локального PMTiles используется нейтральный стиль, а аналитические слои продолжают
работать.

## 3. Clean Architecture без лишних абстракций

```text
apps/web/src/
├── domain/
│   ├── city/          CityDefinition, CityState, StateRevision
│   ├── scenario/      commands, measures, ScenarioDraft
│   └── council/       CouncilResult
├── application/
│   ├── ports/         CityRepository, CityCache, ScenarioEvaluator
│   └── use-cases/     loadCity, applyCommand, evaluate, runCouncil
├── infrastructure/
│   ├── api/           HttpCityRepository, HttpScenarioEvaluator
│   ├── cache/         IndexedDbCityCache
│   └── map/           MapLibreAdapter, DeckOverlayAdapter
└── presentation/
    ├── map/
    ├── dashboard/
    ├── scenario/
    └── council/

packages/contracts/    DTO/OpenAPI types shared by frontend and backend
packages/city-engine/  pure deterministic rules, only if backend is TypeScript
```

Правило зависимостей:

```text
presentation → application → domain
infrastructure ─implements→ application ports
domain imports: no React, no MapLibre, no fetch, no IndexedDB
```

Не делаем repository/use-case на каждый `GET`. Глубокий интерфейс нужен только
для трёх нестабильных границ: transport API, persistent cache и map renderer.

Минимальные порты:

```ts
interface CityRepository {
  listCities(signal?: AbortSignal): Promise<CitySummary[]>;
  getManifest(cityId: string, etag?: string): Promise<ManifestResponse>;
  getPackage(cityId: string, version: string): Promise<CityPackage>;
}

interface ScenarioEvaluator {
  evaluate(input: EvaluateScenario): Promise<EvaluationResult>;
  runCouncil(input: RunCouncil): Promise<CouncilResult>;
}

interface CityCache {
  get(cityId: string, version: string): Promise<CityPackage | null>;
  put(city: CityPackage): Promise<void>;
}
```

## 4. Dynamic City State: мгновенное изменение без гонок

`City State` изменяемый с точки зрения UX, но каждое изменение оформляется новой
ревизией. Это даёт мгновенную карту и воспроизводимый audit.

```ts
interface CitySessionState {
  cityId: string;
  definitionVersion: string;
  baseline: CitySnapshot;
  current: CitySnapshot;
  draft: ScenarioDraft;
  clientRevision: number;
  confirmedRevision: number;
  sync: 'idle' | 'preview' | 'syncing' | 'confirmed' | 'error';
}
```

Алгоритм одного действия:

1. `dispatch(command)` синхронно обновляет `draft` и локальный preview;
2. `clientRevision += 1`;
3. карта и dashboard получают один и тот же derived view model;
4. предыдущий HTTP-запрос отменяется через `AbortController`;
5. после debounce `150–250 ms` отправляется новая ревизия;
6. ответ применяется, только если `accepted_client_revision === clientRevision`;
7. старый ответ отбрасывается без визуального отката;
8. расхождение preview/backend подсвечивается как reconciliation, а backend
   результат становится подтверждённым.

Если frontend и backend написаны на TypeScript, детерминированный City Engine
лучше вынести в `packages/city-engine` и запускать на обеих сторонах. Если backend
на Python, frontend делает только preview по версионированному каталогу эффектов,
а совпадение проверяется общими fixture contract tests.

## 5. Backend API для нескольких городов

### Bootstrap и кеш

```http
GET /api/v1/cities
GET /api/v1/cities/{city_id}/manifest
GET /api/v1/cities/{city_id}/package?version={definition_version}
```

`GET /cities` пока возвращает один элемент, но UI не содержит hardcode `astana`:

```json
{
  "cities": [
    {
      "id": "astana",
      "name": "Астана",
      "definition_version": "official-hackathon-v1",
      "state_version": "baseline-v1",
      "available": true
    }
  ]
}
```

`manifest` возвращает `ETag`. Frontend отправляет `If-None-Match`; `304` означает,
что city package из IndexedDB актуален. Ключ кеша:
`city-package:{city_id}:{definition_version}`. Каталог городов всегда
ревалидируется при старте; last-known copy используется только как offline fallback.

В кеше города лежат definition, baseline, geometry и demo POI. Текущий
пользовательский draft хранится отдельно в session storage и никогда не подменяет
baseline.

### Сценарий

```http
POST /api/v1/cities/{city_id}/scenarios/validate
POST /api/v1/cities/{city_id}/scenarios/evaluate
POST /api/v1/cities/{city_id}/council/simulate
```

Ключевые поля evaluate:

```json
{
  "definition_version": "official-hackathon-v1",
  "base_state_version": "baseline-v1",
  "client_revision": 7,
  "commands": [],
  "include_timeline": true
}
```

Response обязательно возвращает:

```json
{
  "accepted_client_revision": 7,
  "server_state_version": "scenario:sha256:...",
  "scenario_hash": "sha256:...",
  "valid": true,
  "current": {},
  "timeline": [],
  "events": [],
  "audit": []
}
```

WebSocket не нужен. Для долгого AI-совета позже допустим SSE, но карта обновляется
мгновенно локальным reducer, а не через поток с сервера.

## 6. Один view model для карты и dashboard

```ts
interface CityViewModel {
  revision: number;
  score: { value: number; delta: number };
  budget: { spent: number; left: number };
  districts: DistrictViewModel[];
  timeline: QuarterViewModel[];
  forecast: ForecastViewModel;
  activeEvents: MapEventViewModel[];
  layerData: LayerViewModel;
  council?: CouncilViewModel;
}
```

Экран:

```text
┌ City selector ─ Scenario status/version ─ Score/Budget/Critical ┐
├───────────────────────────────┬──────────────────────────────────┤
│ карта 60–65%                  │ вкладки                          │
│ layers / 3D / before-delta    │ Решения · Районы · Прогноз       │
│ hover/select/edit             │ События · Совет города           │
├───────────────────────────────┴──────────────────────────────────┤
│ Q0 ── Q1 ── ... ── Q8 · активные события · play/pause           │
└──────────────────────────────────────────────────────────────────┘
```

Обязательные слои:

1. районы: выбранный показатель/Score;
2. `before / scenario / delta`;
3. меры и пользовательские сценарные объекты;
4. события и critical indicators;
5. POI demo;
6. AI reactions после запуска council.

3D-здания — зрелищный слой, но не источник официальных метрик. Граница `whole
Astana` в MVP означает полное покрытие пяти районов и их показателей; детализированные
здания могут покрывать только demo-area и должны быть так подписаны.

## 7. AI и бюджет токенов

Карта не отправляет LLM GeoJSON, историю движений мыши или все квартальные данные.
AI-совет получает компактный `CouncilInput`:

- `scenario_hash`;
- Score before/after;
- районные дельты и critical indicators;
- выбранные меры;
- audit facts.

Один явный клик `Созвать совет` — один structured request. Стабильный system prompt
и schema идут в кешируемом префиксе, динамический `CouncilInput` — последним.
Основной runtime — `gpt-6-luna`; при ошибке используются provider fallback и затем
детерминированная fixture с тем же JSON-контрактом. Смена slider не вызывает LLM.

## 8. План на троих: 2 часа 40 минут + 20 минут freeze

Работа идёт параллельно по контрактам из этого документа.

| Время | Разработчик 1 — engine/API/cache | Разработчик 2 — Aygerim, frontend/map | Разработчик 3 — agent/integration/docs |
|---|---|---|---|
| 0:00–0:20 | `CityPackage`, evaluate DTO, fixtures | shell UI, MapLibre, neutral style | council DTO, deterministic fixture, README skeleton |
| 0:20–1:00 | `/cities`, manifest/ETag, package, evaluate fixture | районы, choropleth, hover/click, layer toggles | provider adapter/fallback или fixture path, contract test |
| 1:00–1:40 | revision handling, validate/evaluate, audit | reducer, instant map/dashboard update, timeline | council panel, reactions/events, evidence links |
| 1:40–2:10 | backend reconciliation and errors | scenario objects: click or one editable layer | Docker/.env.example/runbook and demo narrative |
| 2:10–2:40 | integration fixes, exact formula check | responsive/polish/loading/error/offline | clean run, screenshots, scoring checklist |
| 2:40–3:00 | только blockers | только blockers | feature freeze, final smoke and README |

Единые checkpoints:

- `+20 мин`: DTO и fixture заморожены;
- `+60 мин`: карта с пятью районами и dashboard работают без backend;
- `+100 мин`: действие мгновенно меняет карту, backend подтверждает revision;
- `+160 мин`: clean demo path работает без ключа;
- последние 20 минут: никаких новых функций.

## 9. Приоритет по критериям жюри

| Критерий | Что демонстрируем |
|---|---|
| Соответствие и работоспособность, 25 | полный путь baseline → решение → карта/метрики → forecast → council |
| Техническая реализация, 25 | revision-safe state, Clean Architecture seams, shared contracts, agent structured output |
| README и воспроизводимость, 25 | Docker, snapshots, fixture mode, без ключа и live Overpass |
| Ценность, 15 | единый dashboard показывает эффект и для города, и для районов |
| Потенциал и оригинальность, 10 | multi-city contract, редактируемые сценарные объекты, AI stakeholder council |

## 10. Что вырезать первым

1. полный 3D-слой зданий всей Астаны;
2. PMTiles preprocessing;
3. `editable-layers`, заменив на click-to-add;
4. анимацию движения и heatmaps;
5. SSE;
6. live Overpass;
7. произвольное перемещение районных границ.

Нельзя вырезать: точный Score, пять районов, мгновенный локальный update, защита от
устаревших ответов, dashboard, offline fixtures и README запуска.

## Источники для технической проверки

- [MapLibre GL JS: 3D buildings](https://maplibre.org/maplibre-gl-js/docs/examples/display-buildings-in-3d/)
- [MapLibre GL JS: GeoJSONSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/)
- [deck.gl: MapboxOverlay](https://deck.gl/docs/api-reference/mapbox/mapbox-overlay)
- [deck.gl: using with MapLibre](https://deck.gl/docs/developer-guide/base-maps/using-with-maplibre)
- [deck.gl-community editable layers](https://visgl.github.io/deck.gl-community/docs/modules/editable-layers/api-reference/editable-geojson-layer)
- [Turf.js documentation](https://turfjs.org/docs/)
- [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [OSM copyright and attribution](https://www.openstreetmap.org/copyright)
- [OSMF tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
- [PMTiles documentation](https://docs.protomaps.com/pmtiles/)

