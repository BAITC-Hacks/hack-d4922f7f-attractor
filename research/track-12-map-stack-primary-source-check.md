# Трек 12: проверка стека динамической карты по первичным источникам

Дата проверки: 23 сентября 2026 года  
Статус: короткий технический decision note для MVP менее чем за 3 часа

## Решение

Для первой рабочей вертикали взять:

```text
MapLibre GL JS
  + локальный versioned GeoJSON snapshot
  + модульные функции Turf.js только для нужных расчётов
  + React state/reducer как единый источник текущего состояния города
```

`deck.gl` не нужен, чтобы показать 3D-здания, включаемые слои, выбор объекта и немедленную перекраску. Добавлять его следует только если в MVP действительно нужны большие GPU-слои или редактирование через `@deck.gl-community/editable-layers`.

Если `deck.gl` всё же нужен, актуальная рекомендуемая интеграция для MapLibre GL JS v4.5.1, v5 и v6 — **`@deck.gl/maplibre` + `MapLibreOverlay`**, а не `@deck.gl/mapbox` + `MapboxOverlay`. [Официальная документация deck.gl: MapLibreOverlay](https://deck.gl/docs/api-reference/maplibre/overview).

## Что подтверждено

| Требование | Проверенный механизм | Вывод для MVP |
|---|---|---|
| 3D-здания | MapLibre имеет штатный style layer `fill-extrusion`; высота и основание задаются через `fill-extrusion-height` и `fill-extrusion-base` | Реализуется без deck.gl. [Пример MapLibre](https://maplibre.org/maplibre-gl-js/docs/examples/display-buildings-in-3d/), [Style Spec](https://maplibre.org/maplibre-style-spec/layers/) |
| Включение слоёв | MapLibre меняет `visibility` слоя через `setLayoutProperty` | Районы, здания, улицы, парки и POI можно включать независимо. [Официальный пример](https://maplibre.org/maplibre-gl-js/docs/examples/filter-symbols-by-toggling-a-list/) |
| Выбор объекта | `queryRenderedFeatures` возвращает отрисованные features под курсором; hover/selection можно хранить в feature state | Клик открывает карточку объекта без перезагрузки данных. [Официальный пример](https://maplibre.org/maplibre-gl-js/docs/examples/get-features-under-the-mouse-pointer/) |
| Мгновенное изменение карты | GeoJSON source обновляется из текущего frontend state; стили MapLibre могут зависеть от properties/feature state | Команда пользователя сначала меняет локальный draft state и карту, затем backend подтверждает результат |
| GPU-overlay | `MapLibreOverlay` поддерживает overlaid/interleaved режимы; `setProps` обновляет слои | Нужен только для дополнительных deck.gl-слоёв. Interleaved требует WebGL2. [Документация](https://deck.gl/docs/api-reference/maplibre/overview) |
| Быстрая перекраска deck.gl | При стабильном `data` `updateTriggers` инвалидирует только зависимый accessor; смена `data` пересобирает GPU buffers | Для выбора района держать геометрию стабильной и менять `getFillColor` через trigger. [Using Layers](https://deck.gl/docs/developer-guide/using-layers), [Performance](https://deck.gl/docs/developer-guide/performance) |
| Рисование и изменение GeoJSON | MapLibre показывает рабочую интеграцию с `maplibre-gl-terradraw`; deck.gl-community предлагает `EditableGeoJsonLayer` | Для timebox безопаснее Terra Draw или один заранее ограниченный edit flow. [Пример Terra Draw](https://maplibre.org/maplibre-gl-js/docs/examples/draw-geometries-with-terra-draw/) |
| Метрики по геометрии | Turf `area` считает геодезическую площадь Polygon/MultiPolygon в м²; есть `length`, `intersect` и другие модульные функции | На клиенте можно пересчитать площадь нового парка и длину улиц. Импортировать отдельные `@turf/*`, а не весь пакет. [Turf area](https://turfjs.org/docs/api/area), [Turf repository](https://github.com/Turfjs/turf) |
| Snapshot OSM | Overpass — read-only API для выборочной выгрузки OSM; ответ содержит timestamp базы | Использовать один раз при подготовке данных, не как runtime-зависимость. [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) |
| Офлайн-подложка | PMTiles — один файл с tiles; официальный JS-клиент подключается к MapLibre через протокол `pmtiles://` | Реальный offline mode возможен, если файл, style, glyphs и sprites локальны. [PMTiles + MapLibre](https://github.com/protomaps/PMTiles/blob/main/js/README.md), [CLI extract](https://docs.protomaps.com/pmtiles/cli) |

## Корректировка исходного предложения

Тезис «MapLibre + deck.gl — единственная связка, закрывающая четыре требования» слишком сильный.

- MapLibre сам закрывает `fill-extrusion`, несколько style layers, visibility, фильтры, click/hover и realtime update.
- MapLibre официально демонстрирует редактирование через Terra Draw.
- deck.gl оправдан для большого количества объектов, специальных GPU-визуализаций или если команда уже уверенно умеет интегрировать его.
- Для современной версии стека использовать `MapLibreOverlay`, а не исторический `MapboxOverlay`.

Практический итог: начать с MapLibre-only вертикали и добавлять deck.gl после работающего сценария. Это уменьшает риск получить две WebGL-модели состояния и незавершённое редактирование к защите.

## Редактирование: что реально брать

### Безопасный вариант в timebox

Один режим «Нарисовать парк» через `maplibre-gl-terradraw`:

1. пользователь рисует Polygon;
2. GeoJSON сохраняется в текущий `CityDraftState`;
3. `@turf/area` считает площадь;
4. чистая функция пересчитывает выбранные метрики;
5. те же данные одновременно обновляют карту и dashboard;
6. backend получает command и `client_revision`, затем подтверждает или корректирует state.

Это демонстрирует реальное изменение модели города и связь `действие → геометрия → метрика → прогноз`, не требуя полноценного GIS-редактора.

### `@deck.gl-community/editable-layers`

Пакет существует и содержит `DrawPolygonMode`, `ModifyMode`, `TranslateMode`; `onEdit` возвращает `updatedData`, которое приложение должно положить обратно в state. Он является successor/fork старого nebula.gl и выпускается в community-репозитории. [Get Started](https://visgl.github.io/deck.gl-community/docs/modules/editable-layers/developer-guide/get-started), [Configuration](https://visgl.github.io/deck.gl-community/docs/modules/editable-layers/developer-guide/configuration), [история перехода с nebula.gl](https://visgl.github.io/deck.gl-community/docs/modules/editable-layers).

Риски для текущего timebox:

- это community module, а не core deck.gl;
- `GeometryCollection` не поддерживается; вход надо нормализовать в Point/LineString/Polygon/Multi*. [Data Model](https://visgl.github.io/deck.gl-community/docs/modules/editable-layers/developer-guide/data-model);
- в публичном tracker есть открытые проблемы интеграции overlay/editing и strict TypeScript для некоторых режимов. [Overlay issue #570](https://github.com/visgl/deck.gl-community/issues/570), [TypeScript issue #676](https://github.com/visgl/deck.gl-community/issues/676);
- совместимость конкретной пары версий MapLibre/deck.gl/editable-layers в этом репозитории — **UNVERIFIED**, пока нет локального smoke-test.

Если пакет всё же берётся, зафиксировать точные версии и сначала за 10 минут проверить `DrawPolygonMode` и `ModifyMode` на минимальном экране. При первом несовместимом поведении вернуться к Terra Draw или одному command-driven действию.

## OSM snapshot и воспроизводимость

Overpass пригоден для одноразовой подготовки данных, но не должен вызываться браузером при каждом запуске. Документация предупреждает, что публичные серверы бывают перегружены, рекомендует cache/rate limit/extracts и не обещает высокую надёжность. [Политика публичных Overpass instances](https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances).

Для воспроизводимости сохранить в репозиторий или release artifact:

```text
data/astana/<snapshot-version>/
  buildings.geojson
  roads.geojson
  traffic-signals.geojson
  green-areas.geojson
  social-objects.geojson
  districts.geojson
  manifest.json
```

`manifest.json` должен содержать дату выгрузки, bbox/полигон выборки, полный Overpass QL, `timestamp_osm_base`, версию конвертера, SHA-256 файлов и лицензионную атрибуцию.

### Риски предложенного bbox

Предложенный bbox `51.09,71.36,51.18,71.50` имеет приблизительно 10 × 10 км на широте Астаны. Это **центр города, а не доказанно вся Астана**. Полнота покрытия всех районов этим bbox — **UNVERIFIED**.

Дополнительные ограничения запроса:

- `way["building"]` не включает здания-мультиполигоны, представленные relations;
- один запрос на все `highway=*` и здания может быть тяжёлым и получить timeout;
- парки/лес могут быть как ways, так и multipolygon relations;
- административные границы OSM могут не совпадать с пятью игровыми районами датасета.

Поэтому для хакатона сначала получить минимальный snapshot центра, проверить размер и геометрию, затем расширять. Границы игровых районов хранить отдельно и версионировать вместе с датасетом.

## «Без ключа» и «офлайн» — разные гарантии

MapLibre, deck.gl, Turf и PMTiles не требуют коммерческого API-ключа, но внешняя style URL или tile URL всё равно требует сеть. Полностью автономное демо требует локально хранить:

- `.pmtiles` cutout;
- MapLibre style JSON;
- glyphs/fontstack;
- sprites;
- GeoJSON/PMTiles тематических слоёв;
- корректную OSM attribution.

Protomaps прямо поддерживает `pmtiles extract INPUT OUTPUT --bbox=...` и `--maxzoom`; каждый дополнительный zoom примерно удваивает размер cutout. Для timebox достаточно zoom 0–14 или 0–15 после проверки размера. [PMTiles CLI](https://docs.protomaps.com/pmtiles/cli), [Protomaps Basemap Downloads](https://docs.protomaps.com/basemaps/downloads).

Если локальный PMTiles ещё не подготовлен, оставить нейтральный локальный background style как обязательный fallback, а сетевую подложку — как enhancement. Так основной сценарий с районами, мерами и метриками остаётся работоспособным без сети.

## Лицензии и практические обязательства

| Компонент/данные | Лицензия | Что сделать |
|---|---|---|
| MapLibre GL JS | BSD-3-Clause | Сохранить copyright/license notice. [Проект](https://github.com/maplibre/maplibre-gl-js) |
| deck.gl | MIT | Сохранить license notice. [LICENSE](https://github.com/visgl/deck.gl/blob/master/LICENSE) |
| deck.gl-community | MIT | Сохранить license notice; pin version. [Repository](https://github.com/visgl/deck.gl-community) |
| Turf.js | MIT | Сохранить license notice. [Repository](https://github.com/Turfjs/turf) |
| PMTiles implementation | BSD-3-Clause; specification CC0/public domain | Лицензия кода не определяет лицензию tileset. [PMTiles LICENSE](https://github.com/protomaps/PMTiles/blob/main/LICENSE) |
| OpenStreetMap data | ODbL | Видимая атрибуция OpenStreetMap; проверить обязанности для распространяемой базы/Produced Work. [OSM Copyright](https://www.openstreetmap.org/copyright) |
| Protomaps basemap | ODbL Produced Work | Не hotlink daily build; использовать собственный cutout и OSM attribution. [Downloads](https://docs.protomaps.com/basemaps/downloads) |

Юридическая трактовка производной базы для конкретной комбинации отредактированного OSM snapshot и игровых данных — **UNVERIFIED**; этот документ не является юридической консультацией.

## План на оставшееся время

| Время | Результат | Стоп-условие |
|---:|---|---|
| 0–20 мин | MapLibre открывает локальный GeoJSON районов на нейтральном style; слои имеют стабильные IDs | Если OSM snapshot ещё не готов, не ждать Overpass: использовать уже имеющуюся геометрию/fallback |
| 20–55 мин | Районы, здания или псевдо-экструзия, улицы/парки/POI; переключатели visibility | Не подключать deck.gl, пока базовые слои не работают |
| 55–85 мин | Click/hover, выбранный район, синхронная карточка и dashboard metric | Один state object управляет картой и dashboard |
| 85–120 мин | Один edit flow «Нарисовать парк» и Turf area; мгновенный optimistic recalc | При проблеме с editor заменить на command «добавить парк в выбранную зону» |
| 120–145 мин | Интеграция backend command/evaluate с `client_revision`; stale responses игнорируются | Fixtures остаются доступными при отказе API |
| 145–165 мин | Offline/keyless fallback, attribution, error/loading states | Сетевая подложка не должна быть обязательной |
| 165–180 мин | Smoke-test основного сценария и README с точной командой запуска | Новые визуальные функции не добавлять |

### Scope lock

Обязательная демонстрация:

```text
выбор района
→ действие/редактирование
→ мгновенная смена карты
→ пересчёт одной доказуемой метрики
→ обновление dashboard/прогноза
→ объяснение AI-совета
```

Оставить после MVP: произвольное изменение границ районов, полноценное редактирование дорог, snapping, Cesium/photogrammetry, live Overpass, собственный tile server и синхронное редактирование несколькими пользователями.

## UNVERIFIED перед feature freeze

- фактический размер и полнота Astana OSM snapshot;
- доля зданий Астаны с `height` или `building:levels`;
- совместимость выбранных npm-версий в текущем проекте;
- время и размер PMTiles cutout при выбранном `maxzoom`;
- соответствие OSM district relations пяти районам хакатонного датасета;
- отсутствие скрытых внешних font/sprite URLs в offline style;
- производительность Turf на фактическом количестве features.
