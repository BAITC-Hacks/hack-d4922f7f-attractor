# Динамическая послойная карта Астаны: frontend-архитектура и API-контракт MVP

Дата: 23 сентября 2026 года  
Статус: практическая спецификация для реализации за 2–3 часа  
Контекст: официальный хакатонный датасет с 5 районами, 10 показателями, 14 мерами и горизонтом 8 кварталов

## Короткое решение

Для MVP использовать **React + TypeScript + MapLibre GL JS**, локальный GeoJSON пяти игровых районов и один детерминированный ответ backend, содержащий все девять состояний `Q0…Q8`. Не нужны ни GIS-сервер, ни `deck.gl`, ни WebSocket.

Карта должна быть не самостоятельной системой прогнозирования, а географическим представлением результата City Engine:

```text
dataset + 5 выбранных мер
          ↓
POST /api/v1/scenarios/evaluate
          ↓
baseline + Q0…Q8 + audit events + council result
          ↓
MapLibre: районы + меры + POI + события + реакции агентов
```

Главное ограничение: датасет фиксирует **5 районов**, но актуальный официальный план развития Астаны перечисляет уже **6 районов**, включая Сарайшык. Значит, геометрия должна иметь `dataset_version` и быть заморожена вместе с правилами симуляции. Нельзя незаметно взять актуальные шесть полигонов и показать числа пяти районов на другой административной сетке. [Официальный план развития Астаны на 2026–2030 годы](https://www.gov.kz/memleket/entities/astana/documents/details/940185?lang=ru), [официальный паспорт города на 01.02.2026](https://www.gov.kz/memleket/entities/astana/documents/details/975994?lang=ru).

## 1. Выбор картографического стека

| Вариант | Лицензия/условия | Сильная сторона | Риск для MVP | Решение |
|---|---|---|---|---|
| **MapLibre GL JS** | BSD-3-Clause, [LICENSE проекта](https://github.com/maplibre/maplibre-gl-js/blob/main/LICENSE.txt) | WebGL, GeoJSON/vector/raster sources, data-driven styles, динамическое обновление source/feature state | Нужно один раз правильно настроить style/source/layers | **Выбрать** |
| Mapbox GL JS | Коммерческие [Mapbox Terms of Service](https://www.mapbox.com/legal/tos) | Очень зрелые стили, basemap и инструменты Mapbox | Access token, тарифы и зависимость от внешнего сервиса; для пяти полигонов преимуществ почти нет | Не брать в обязательный контур |
| deck.gl | MIT, [LICENSE проекта](https://github.com/visgl/deck.gl/blob/master/LICENSE) | Большие объёмы точек, heatmap, arcs, 3D и GPU-агрегации | Лишний слой сложности для 5 полигонов и десятков POI | Оставить как развитие |
| Leaflet | BSD-2-Clause, [LICENSE проекта](https://github.com/Leaflet/Leaflet/blob/main/LICENSE) | Самый простой 2D GeoJSON/raster map | Менее удобная единая WebGL-модель для нескольких data-driven слоёв и последующего роста | Допустимый fallback, если команда уже знает Leaflet |

Почему MapLibre:

- `GeoJSONSource` умеет менять данные и перерисовывать карту; `updateData` поддерживает частичные обновления при наличии уникальных feature IDs. Для пяти районов достаточно обычного `setData`. [MapLibre `GeoJSONSource`](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/)
- MapLibre позволяет добавлять GeoJSON sources и `fill`, `line`, `circle`, `symbol` layers и управлять ими через один style graph. [MapLibre Map API](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/), [пример GeoJSON polygon](https://maplibre.org/maplibre-gl-js/docs/examples/add-a-geojson-polygon/)
- Mapbox использует ту же модель `source → layer`, причём официальная документация отдельно рекомендует style layers для большого количества объектов и динамической стилизации. Это подтверждает сам подход, но не создаёт причины брать платный hosted-контур для MVP. [Mapbox: add your data](https://docs.mapbox.com/mapbox-gl-js/guides/add-your-data/style-layers/)
- `deck.gl` действительно умеет отображать GeoJSON как полигоны, линии и точки и имеет heatmap/hexagon/MVT layers, но эти возможности не нужны для пяти районов. [deck.gl `GeoJsonLayer`](https://deck.gl/docs/api-reference/layers/geojson-layer), [каталог слоёв deck.gl](https://deck.gl/docs/api-reference/layers)
- Leaflet официально поддерживает GeoJSON и функцию стиля по properties, поэтому остаётся рабочим запасным вариантом. [Leaflet GeoJSON reference](https://leafletjs.com/reference#geojson)

### Рекомендуемый frontend stack

```text
Vite + React + TypeScript
MapLibre GL JS
Zustand или React state/reducer
TanStack Query — только если уже установлен; иначе обычный fetch
CSS/Tailwind — по текущему стеку команды
```

Не добавлять `deck.gl`, Turf, PostGIS или геокодер, пока конкретная функция без них не реализуема.

## 2. Источники геоданных и ограничения лицензий

### 2.1. Базовая карта

Для онлайн-демо допустим basemap на данных OpenStreetMap, но данные и tile-сервис — разные вещи:

- данные OSM лицензированы по ODbL и требуют атрибуции OpenStreetMap и contributors; производная база также имеет share-alike условия. [OSM Copyright and License](https://www.openstreetmap.org/copyright)
- публичный `tile.openstreetmap.org` не имеет SLA, требует видимой атрибуции и соблюдения cache policy, запрещает массовую предзагрузку и offline-пакеты. [OSMF Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)

Практическое решение:

1. **Основной online mode:** MapLibre + выбранный командой hosted OSM-derived style/provider согласно его условиям и ключу.
2. **Обязательный demo fallback:** локальный neutral style без внешних tiles — светлый фон, река/главные дороги при наличии локального GeoJSON и поверх них пять районов.
3. Не скачивать тайлы с `tile.openstreetmap.org` для Docker/offline: политика OSMF это прямо запрещает.

Нейтральный style гарантирует, что основной сценарий продолжит работать без интернета и токена:

```json
{
  "version": 8,
  "sources": {},
  "layers": [
    {"id": "background", "type": "background", "paint": {"background-color": "#F5F7FA"}}
  ]
}
```

### 2.2. Границы районов

Есть три уровня источника:

1. **Официальное юридическое/визуальное подтверждение:** решения акимата и материалы генплана. Официальная публикация 2022 года устанавливает границы Алматы, Байконыра, Есиля, Сарыарки и нового района; официальный материал по созданию Нуры содержит картосхему и словесное описание. [решение об образовании нового района](https://www.gov.kz/memleket/entities/astana/documents/details/375774?lang=ru), [карта и описание Нуры/Есиля](https://www.gov.kz/uploads/2023/6/27/d6104b4749d10f8888d99069a1dc947a_original.2635760.pdf)
2. **Машиночитаемая геометрия для прототипа:** одноразовый экспорт административных relations из OpenStreetMap через Overpass, сохранённый в репозитории как GeoJSON с атрибуцией и датой snapshot. Overpass — read-only API для выборки частей OSM по типу, тегам и географии. [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
3. **UI fallback:** вручную упрощённые полигоны, явно помеченные `geometry_accuracy: illustrative`, если корректный экспорт не готов к feature freeze.

Наличие официального публичного API, который прямо отдаёт актуальные границы районов Астаны в GeoJSON, в ходе этого исследования **UNVERIFIED**. Официальный геоинформационный портал заявляет отображение границ городов, районов и округов, но опубликованная страница не документирует открытый GeoJSON/WFS API. [Геоинформационный портал г. Астана](https://www.gov.kz/memleket/entities/astana/activities/15951?lang=ru&parentId=360)

### 2.3. Как согласовать 5 игровых и 6 актуальных районов

Вариант для MVP:

```text
geometry_version = astana-dataset-5-v1
dataset_version  = official-hackathon-v1
districts        = esil, almaty, saryarka, baikonyr, nura
```

- Не показывать Сарайшык как шестой интерактивный район: для него нет строки показателей и population share в выданном датасете.
- Если исходная geometry взята из актуального шестирайонного OSM snapshot, backend/preprocessing должен восстановить игровую геометрию через `union(current_almaty, sarayshyq)` **только после визуальной проверки** по официальной пятирайонной картосхеме. Официальный акимат описывал создание шестого района как разделение Алматы. [сообщение акимата о шестом районе](https://www.gov.kz/memleket/entities/astana/press/news/details/791094?lang=ru)
- В UI показывать badge: `Игровая модель · геометрия по версии датасета (5 районов)`.
- В README объяснить расхождение одной фразой и не называть слой актуальной административной картой.

### 2.4. POI и инфраструктура

Приоритет источников:

1. **Локальные demo fixtures** из 20–50 точек, проверенных командой: школы, поликлиники, парки, остановки, объекты ЖКХ. Для хакатона это надёжнее live-запросов.
2. Официальный портал открытых данных Казахстана поддерживает API datasets и геополя; официальные примеры показывают geospatial query для медицинских организаций. [примеры API data.egov.kz](https://data.egov.kz/pages/samples)
3. В каталоге есть государственные datasets медицинских организаций и школ, однако часть наборов архивна, а наличие координат и свежесть нужно проверять у конкретной версии. [медицинские организации](https://data.egov.kz/datasets/view?index=medorg), [реестр школ](https://data.egov.kz/datasets/view?index=rosogrz_mp)
4. OSM/Overpass можно использовать для единовременного извлечения POI (`amenity=school`, `amenity=clinic|hospital`, `leisure=park`, `highway=bus_stop`) при сохранении snapshot и OSM attribution.

POI являются контекстом интерфейса. Они **не должны менять Score**, потому что официальная формула получает исходные 10 индексов, а не пересчитывает их из количества точек на карте.

## 3. Модель слоёв карты

Порядок снизу вверх:

| ID слоя | Геометрия | Назначение | Источник |
|---|---|---|---|
| `basemap` | vector/raster | дороги, вода, подписи | online provider или neutral offline style |
| `city-boundary` | line | контур всей Астаны | локальный versioned GeoJSON |
| `district-fill` | fill | choropleth выбранного показателя/районного score | те же 5 features + runtime state |
| `district-delta` | fill | режим `после − до` с diverging palette | `DistrictSnapshot.delta` |
| `district-outline` | line | границы, hover/selected | feature state |
| `district-label` | symbol | название и `D_d` | properties/state |
| `poi-clusters` | circle/symbol | школы, медицина, парки, остановки | локальный snapshot; optional |
| `measure-points` | symbol | размещённые районные меры | координата/callout внутри района |
| `measure-impact` | circle/fill | радиус/зона прямого воздействия | только объяснительная визуализация |
| `event-pulse` | circle | старт, созревание эффекта, синергия, снятие critical | derived audit events |
| `agent-reactions` | symbol/circle | sentiment/поддержка по району | council result |
| `selection` | line | активный район | frontend state |

### Режимы карты

```ts
type MapMode = 'baseline' | 'scenario' | 'delta';
type IndicatorId = 'score' | 'T1' | 'T2' | 'E1' | 'E2' |
  'S1' | 'S2' | 'B1' | 'B2' | 'C1' | 'C2';
```

- `baseline`: всегда `Q0`, исходное значение.
- `scenario`: значение на выбранном квартале `Q0…Q8`.
- `delta`: `scenario(q) − baseline`; ноль нейтральный, улучшение зелёное/синее, ухудшение красное.
- `score`: заливка по `district_score`; выбранный показатель — по его значению `0…100`.
- Порог `<40` должен иметь отдельный hatch/alert, а не только другой оттенок.

### Timeline

Backend обязан вернуть готовые snapshots на каждом квартале. Frontend не вычисляет лаги и синергии:

```text
Q0 ─ Q1 ─ Q2 ─ Q3 ─ Q4 ─ Q5 ─ Q6 ─ Q7 ─ Q8
      ↑ M9/M10/M12/M14
           ↑ M1/M2/M4/M6
                ↑ M5/M7/M8
                     ↑ M3/M13
```

Пользователь двигает slider; frontend выбирает `timeline[quarter]`, обновляет feature state и список активных событий. Важная оговорка: исходная формула задаёт итоговую реализованную долю `(8−L)/8`, но не описывает точную кривую по каждому промежуточному кварталу. Поэтому backend должен либо:

- вернуть только `Q0` и `Q8`, если промежуточная динамика не утверждена;
- либо явно зафиксировать `timeline_model: "linear_after_lag_v1"` и считать Q1–Q7 объяснительным режимом, не новой официальной формулой.

## 4. Backend API: обязательный контракт

Все числовые расчёты выполняются backend. Frontend только выбирает сценарий и отображает ответ.

### `GET /api/v1/model`

Один bootstrap-запрос: версия, показатели, правила, каталог мер и map manifest.

```json
{
  "dataset_version": "official-hackathon-v1",
  "geometry_version": "astana-dataset-5-v1",
  "horizon_quarters": 8,
  "budget_limit": 100,
  "decision_count": 5,
  "districts": [
    {"id": "esil", "name": "Есиль", "population_share": 0.27},
    {"id": "almaty", "name": "Алматы", "population_share": 0.24},
    {"id": "saryarka", "name": "Сарыарка", "population_share": 0.20},
    {"id": "baikonyr", "name": "Байконур", "population_share": 0.13},
    {"id": "nura", "name": "Нура", "population_share": 0.16}
  ],
  "indicators": [
    {"id": "T1", "domain": "transport", "name": "Разгрузка дорог", "weight": 0.10}
  ],
  "measures": [
    {
      "id": "M7",
      "name": "Школа + детсад",
      "domain": "social",
      "scope": "district",
      "cost": 24,
      "lag_quarters": 3,
      "effects": {"S1": 16}
    }
  ],
  "map": {
    "districts_url": "/api/v1/map/districts?geometry_version=astana-dataset-5-v1",
    "pois_url": "/api/v1/map/pois",
    "geometry_accuracy": "dataset-aligned",
    "attribution": "© OpenStreetMap contributors, ODbL"
  }
}
```

### `GET /api/v1/map/districts?geometry_version=astana-dataset-5-v1`

Возвращает `FeatureCollection<Polygon|MultiPolygon>`. `feature.id` обязателен и равен `district_id`, чтобы MapLibre мог применять feature state.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "nura",
      "properties": {
        "district_id": "nura",
        "name": "Нура",
        "geometry_version": "astana-dataset-5-v1"
      },
      "geometry": {
        "type": "MultiPolygon",
        "coordinates": [[[[71.35, 51.10], [71.50, 51.10], [71.50, 51.20], [71.35, 51.10]]]]
      }
    }
  ],
  "meta": {
    "source": "OpenStreetMap snapshot, reconciled to dataset",
    "snapshot_date": "2026-09-23",
    "license": "ODbL-1.0"
  }
}
```

### `GET /api/v1/map/pois?categories=school,clinic,park,bus_stop`

Опциональный endpoint. Для MVP можно вернуть один локальный FeatureCollection без bbox/pagination.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "poi-school-01",
      "properties": {
        "category": "school",
        "name": "Школа",
        "district_id": "nura",
        "source": "demo-fixture"
      },
      "geometry": {"type": "Point", "coordinates": [71.42, 51.12]}
    }
  ]
}
```

### `POST /api/v1/scenarios/validate`

Быстрая валидация при изменении набора.

Request:

```json
{
  "dataset_version": "official-hackathon-v1",
  "decisions": [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12"},
    {"measure_id": "M5", "district_id": "saryarka"}
  ]
}
```

Response:

```json
{
  "valid": true,
  "budget": {"spent": 95, "left": 5, "limit": 100},
  "violations": [],
  "warnings": []
}
```

Ошибка возвращается структурно, без парсинга текста:

```json
{
  "valid": false,
  "budget": {"spent": 106, "left": -6, "limit": 100},
  "violations": [
    {"code": "BUDGET_EXCEEDED", "message": "Бюджет превышен на 6"},
    {"code": "MEASURES_CONFLICT", "measure_ids": ["M1", "M3"]}
  ]
}
```

### `POST /api/v1/scenarios/evaluate`

Главный endpoint. Request совпадает с validate и добавляет параметры timeline.

```json
{
  "dataset_version": "official-hackathon-v1",
  "decisions": [
    {"measure_id": "M7", "district_id": "nura"},
    {"measure_id": "M8", "district_id": "nura"},
    {"measure_id": "M10", "district_id": "nura"},
    {"measure_id": "M12"},
    {"measure_id": "M5", "district_id": "saryarka"}
  ],
  "include_timeline": true,
  "timeline_model": "linear_after_lag_v1"
}
```

Сокращённый response:

```json
{
  "scenario_id": "scn_01",
  "scenario_hash": "sha256:...",
  "dataset_version": "official-hackathon-v1",
  "valid": true,
  "budget": {"spent": 95, "left": 5},
  "score": {
    "before": 52.55768,
    "after": 56.54307,
    "delta": 3.98539,
    "d_avg": 58.0776,
    "min_district_id": "nura",
    "min_district_score": 52.9625,
    "critical_before": 2,
    "critical_after": 0
  },
  "timeline_model": "linear_after_lag_v1",
  "timeline": [
    {
      "quarter": 0,
      "city_score": 52.55768,
      "districts": {
        "nura": {
          "district_score": 49.18,
          "critical_count": 2,
          "indicators": {"T1": 55, "T2": 40, "E1": 45, "E2": 65, "S1": 38, "S2": 35, "B1": 55, "B2": 50, "C1": 60, "C2": 50},
          "delta": {"T1": 0, "T2": 0, "E1": 0, "E2": 0, "S1": 0, "S2": 0, "B1": 0, "B2": 0, "C1": 0, "C2": 0}
        }
      },
      "events": []
    },
    {
      "quarter": 8,
      "city_score": 56.54307,
      "districts": {
        "nura": {
          "district_score": 52.9625,
          "critical_count": 0,
          "indicators": {"S1": 48, "S2": 43.75, "B1": 67.5, "B2": 51.75, "C2": 54.375},
          "delta": {"S1": 10, "S2": 8.75, "B1": 12.5, "B2": 1.75, "C2": 4.375}
        }
      },
      "events": ["evt_m7_effect", "evt_nura_critical_resolved"]
    }
  ],
  "events": [
    {
      "id": "evt_nura_critical_resolved",
      "quarter": 3,
      "type": "critical_resolved",
      "district_id": "nura",
      "indicator_ids": ["S1", "S2"],
      "severity": "positive",
      "title": "Нура вышла из критической зоны",
      "evidence_refs": ["audit:S1:nura", "audit:S2:nura"]
    }
  ],
  "audit": [
    {
      "ref": "audit:S1:nura",
      "district_id": "nura",
      "indicator_id": "S1",
      "before": 38,
      "terms": [{"measure_id": "M7", "raw_effect": 16, "maturity": 0.625, "applied": 10}],
      "after": 48
    }
  ]
}
```

Точные значения baseline должны совпадать с выданным датасетом. Frontend не хранит собственную копию формулы.

### `POST /api/v1/council/simulate`

Agent layer запускается только после успешного `evaluate`.

```json
{
  "scenario_id": "scn_01",
  "scenario_hash": "sha256:...",
  "mode": "auto"
}
```

```json
{
  "mode": "deterministic",
  "support": 0.68,
  "districts": {
    "nura": {"support": 0.84, "sentiment": "positive", "top_concern": "Транспорт не улучшен"},
    "esil": {"support": 0.49, "sentiment": "mixed", "top_concern": "Нет прямых районных мер"}
  },
  "reactions": [
    {
      "id": "reaction_01",
      "agent_id": "nura_parent_01",
      "district_id": "nura",
      "support": 0.82,
      "message": "Школьный дефицит снижается, но доступность транспорта остаётся без изменений.",
      "evidence_refs": ["audit:S1:nura"]
    }
  ],
  "coalitions": [
    {"id": "coalition_social", "label": "Сторонники социальных вложений", "district_ids": ["nura"]}
  ],
  "recommendation": {
    "type": "swap",
    "remove_measure_id": "M10",
    "add_measure_id": "M1",
    "district_id": "nura",
    "requires_recalculation": true
  }
}
```

Рекомендация агента не меняет карту сама. UI создаёт новый draft, вызывает `validate`, затем `evaluate`.

## 5. Frontend state schema

```ts
type DistrictId = 'esil' | 'almaty' | 'saryarka' | 'baikonyr' | 'nura';

interface AppState {
  model: ModelDefinition | null;
  draft: {
    decisions: Array<{ measureId: string; districtId?: DistrictId }>;
    validation: ValidationResult | null;
  };
  evaluation: EvaluationResult | null;
  council: CouncilResult | null;
  map: {
    mode: 'baseline' | 'scenario' | 'delta';
    quarter: 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
    indicatorId: 'score' | IndicatorId;
    selectedDistrictId: DistrictId | null;
    hoveredDistrictId: DistrictId | null;
    visibleLayers: {
      pois: boolean;
      measures: boolean;
      events: boolean;
      reactions: boolean;
    };
  };
  ui: {
    evaluating: boolean;
    simulatingCouncil: boolean;
    error: ApiError | null;
  };
}
```

### Runtime feature state

MapLibre feature state для каждого района:

```ts
interface DistrictFeatureState {
  value: number;
  baseline: number;
  delta: number;
  districtScore: number;
  criticalCount: number;
  support?: number;
  selected: boolean;
  hovered: boolean;
}
```

Geometry остаётся immutable. При перемещении slider меняется только feature state; это исключает повторную загрузку полигонов.

## 6. Событийная схема

Нужно различать три типа событий:

1. `domain events` — факты City Engine, подтверждённые расчётом;
2. `agent events` — реакции synthetic population;
3. `ui events` — click/hover/slider, не сохраняются в доменной модели.

```ts
type SimulationEventType =
  | 'measure_started'
  | 'measure_effect_started'
  | 'synergy_activated'
  | 'critical_resolved'
  | 'critical_created'
  | 'indicator_changed'
  | 'agent_reaction';

interface SimulationEvent {
  id: string;
  quarter: number;
  type: SimulationEventType;
  districtId?: DistrictId;
  measureIds?: string[];
  indicatorIds?: IndicatorId[];
  severity: 'positive' | 'neutral' | 'warning';
  title: string;
  description?: string;
  evidenceRefs: string[];
}
```

Каждое утверждение в popup должно вести к `audit` или agent evidence. Нельзя создавать «пробку», «аварию» или «смог» как случайное событие, если такого модификатора нет в официальной спецификации: это изменит смысл Score. Случайные city shocks можно добавить позже только отдельным sandbox-режимом с явным badge `неофициальный сценарий`.

## 7. Нужны ли WebSocket или SSE

**Для MVP — нет.** Все городские состояния детерминированы, объём ответа мал: 5 районов × 10 показателей × 9 кварталов — всего 450 числовых значений плюс audit. Один `POST /evaluate` возвращает всё состояние.

Для council за 2–3 часа выбрать:

- синхронный `POST /council/simulate` с timeout 8–12 секунд;
- loading steps на frontend (`готовим персоны → обсуждаем → собираем отчёт`) как визуальный статус;
- deterministic fallback с тем же JSON-контрактом.

SSE оправдан позже, если нужно реально стримить десятки agent reactions. Тогда контракт:

```text
POST /api/v1/council/jobs              → 202 {job_id}
GET  /api/v1/council/jobs/{id}/events  → text/event-stream
GET  /api/v1/council/jobs/{id}         → final result
```

WebSocket не нужен: клиент не отправляет постоянный двусторонний поток команд, а reconnect/state recovery усложнят демо.

## 8. Performance и offline/Docker fallback

### Performance budget

- 5 district features и до 100 POI — обычный GeoJSON, vector tiles не нужны.
- Simplify geometry до визуально достаточного уровня; цель — district GeoJSON менее 300–500 KB gzip, но не ценой заметных дыр между районами.
- Один source `districts`, несколько style layers; не создавать пять отдельных React markers для полигонов.
- Для большого количества POI использовать MapLibre circle/symbol layer и clustering, а не DOM markers.
- Не пересоздавать `Map` при смене квартала; обновлять feature state/paint expressions.
- Анимацию quarter transition ограничить 250–400 ms и отключать при `prefers-reduced-motion`.
- Цвета не должны быть единственным носителем значения: label, число и critical icon обязательны.

### Offline/Docker mode

В репозитории должны лежать:

```text
public/map/astana-districts-5-v1.geojson
public/map/astana-pois-demo-v1.geojson
public/map/neutral-style.json
src/fixtures/model.json
src/fixtures/evaluation-example.json
src/fixtures/council-example.json
```

Переменная окружения:

```text
VITE_MAP_MODE=offline|online
VITE_MAP_STYLE_URL=<optional hosted style>
```

Если online style не загрузился за 3 секунды, UI переключается на `neutral-style.json`, сохраняет районы, scenario и council и показывает ненавязчивый badge `Базовая карта недоступна — аналитические слои работают`.

Никакой внешний API не должен быть необходим для воспроизведения fixture demo.

## 9. Реалистичный scope на 2–3 часа

### 0:00–0:20 — зафиксировать контракт

- согласовать `DistrictId`, `IndicatorId`, request/response `evaluate`;
- положить валидный GeoJSON пяти районов или illustrative fallback;
- проверить `feature.id` для всех пяти features;
- заморозить layer IDs и палитру.

### 0:20–1:00 — рабочая карта

- MapLibre canvas + neutral/offline style;
- district fill/outline/labels;
- selector показателя;
- hover/click popup;
- переключатель `до / после / дельта` на fixture.

### 1:00–1:40 — интеграция сценария

- подключить `POST /evaluate`;
- quarter slider;
- measure markers;
- critical state `<40`;
- score card и district details.

### 1:40–2:10 — события и council

- event markers/pulses из backend events;
- reactions per district;
- один popup с `support`, concern и evidence;
- suggested swap создаёт draft, но не применяется автоматически.

### 2:10–2:40 — отказоустойчивость

- offline style fallback;
- fixture response при недоступном backend/LLM;
- invalid scenario UI;
- проверка Docker clean run.

### 2:40–3:00 — demo polish

- один предзагруженный пример `M7 Нура + M8 Нура + M10 Нура + M12 + M5 Сарыарка`;
- репетиция пути `52.55768 → 56.54307`;
- проверить attribution и badge пятирайонной версии;
- feature freeze.

### Что вырезать первым

1. live POI API;
2. clusters и heatmap;
3. плавную анимацию timeline;
4. SSE;
5. 3D/extrusion;
6. любые случайные события;
7. настоящий live multi-agent UI — оставить готовый deterministic response.

Нельзя вырезать: пятирайонную карту, before/after/delta, точный Score, critical states, audit evidence, offline fixture и объяснение расхождения `5 районов в датасете / 6 районов сейчас`.

## 10. Definition of done для frontend

- Карта запускается без internet и без API key.
- Пять районов имеют стабильные IDs и совпадают с пятью строками датасета.
- Baseline показывает исходные значения из датасета.
- Пример организаторов показывает `52.55768 → 56.54307` без расчёта на клиенте.
- Slider не меняет geometry, а только state выбранного квартала.
- Слои мер, событий, POI и реакций можно независимо выключить.
- Любое число в popup приходит из `EvaluationResult` или `CouncilResult` и имеет evidence reference.
- Ошибка basemap не ломает scenario flow.
- На карте видна атрибуция источника геометрии/подложки.
- UI явно сообщает, что это пятирайонная версия игровой модели, а не актуальная кадастровая карта.

## Источники

- [MapLibre GL JS API: Map](https://maplibre.org/maplibre-gl-js/docs/API/classes/Map/)
- [MapLibre GL JS API: GeoJSONSource](https://maplibre.org/maplibre-gl-js/docs/API/classes/GeoJSONSource/)
- [MapLibre: add a GeoJSON polygon](https://maplibre.org/maplibre-gl-js/docs/examples/add-a-geojson-polygon/)
- [Mapbox GL JS: style layers and data sources](https://docs.mapbox.com/mapbox-gl-js/guides/add-your-data/style-layers/)
- [deck.gl GeoJsonLayer](https://deck.gl/docs/api-reference/layers/geojson-layer)
- [Leaflet GeoJSON reference](https://leafletjs.com/reference#geojson)
- [OpenStreetMap Copyright and License](https://www.openstreetmap.org/copyright)
- [OpenStreetMap Foundation Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/)
- [OpenStreetMap Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API)
- [Официальный геоинформационный портал Астаны](https://www.gov.kz/memleket/entities/astana/activities/15951?lang=ru&parentId=360)
- [Официальное решение об установлении границ районов, 2022](https://www.gov.kz/memleket/entities/astana/documents/details/375774?lang=ru)
- [Официальная карта и описание границ Нуры/Есиля](https://www.gov.kz/uploads/2023/6/27/d6104b4749d10f8888d99069a1dc947a_original.2635760.pdf)
- [Официальный план развития Астаны на 2026–2030 годы](https://www.gov.kz/memleket/entities/astana/documents/details/940185?lang=ru)
- [Официальный паспорт города на 01.02.2026](https://www.gov.kz/memleket/entities/astana/documents/details/975994?lang=ru)
- [Официальные примеры API открытых данных Казахстана](https://data.egov.kz/pages/samples)
