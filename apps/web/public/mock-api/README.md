# Mock API fixtures

Статические тела DTO из `packages/contracts/src/v1.ts` для API-first интерфейса V1. Файлы `*.response.json` моделируют ответ; остальные кроме `catalog.json` — тела POST-запросов. Каждый POST-запрос содержит все четыре версии каталога.

| Файл | Endpoint | Назначение |
|---|---|---|
| `catalog.json` | `GET /catalog` | `CatalogResponse`: пять районов с `indicators`, 10 полных показателей, 14 мер и `rules` |
| `validate-valid.json` | `POST /v1/validate` | Запрос с допустимым контрольным набором |
| `validate-valid.response.json` | `POST /v1/validate` | Ответ: valid, цена и остаток |
| `validate-invalid.json` | `POST /v1/validate` | Запрос с повтором, конфликтами и неверным районом |
| `validate-invalid.response.json` | `POST /v1/validate` | Ответ с issues |
| `evaluate-golden.json` | `POST /v1/evaluate` | Запрос контрольного сценария |
| `evaluate-golden.response.json` | `POST /v1/evaluate` | Полный `EvaluateResponse`; golden: `52.55768 → 56.54307` |
| `evaluate-invalid.json` | `POST /v1/evaluate` | Запрос с невалидным набором из пяти выборов |
| `evaluate-invalid.response.json` | `POST /v1/evaluate` | Полный невалидный `EvaluateResponse`: сводные поля и decomposition null, массивы пусты |
| `alternatives.json` | `POST /v1/alternatives` | Поиск с ограничениями по бюджету и числу выборов |
| `alternatives.response.json` | `POST /v1/alternatives` | `AlternativesResponse` с одной допустимой альтернативой и вложенным полным `EvaluateResponse` |
| `astana-districts.geojson` | GeoJSON asset (не API endpoint) | Официальные геометрии шести районов; стабильные ID V1, Сарайшык `in_v1_model: false` |

Схемы запросов используют `{ "versions": { "catalogVersion": "official-v1", "dataSnapshotId": "astana-v1-source-dataset", "modelVersion": "official-v1", "rulesVersion": "official-v1" }, "selections": [{ "measureId": "M7", "districtId": "nura" }] }`; у городских мер `districtId` равен `null`. Канонические ID районов: `esil`, `almaty`, `saryarka`, `baykonur`, `nura`. Районные baseline values и правила перенесены из исходного набора и контракта V1. Fixtures не содержат динамической V2 временной шкалы. Внешние зависимости не нужны.

GeoJSON скопирован из официального [ArcGIS FeatureServer layer 0](https://gis.esaulet.kz/server/rest/services/Hosted/raiony/FeatureServer/0), локальный исходный файл `/private/tmp/astana-raiony.geojson`; источник указан на 2026-09-23. Сохранены все шесть объектов слоя и их геометрии/исходные свойства; добавлены стабильные свойства `id` (сопоставлены по `name_object`) и `in_v1_model` (у Сарайшыка objectid 11 — false, у остальных true). Совместимость геометрий с пятью районами V1 и агрегация 6→5 не валидированы.
