# Визуальные схемы для README

Этот файл — production-бриф для растровых иллюстраций README. Схемы должны объяснять
архитектуру, а не изображать несуществующий интерфейс. Реализованные компоненты
показываются сплошной линией, запланированные — пунктиром с явной подписью «план».

## Общие требования

- Формат: PNG, 1600×900, до 2 МБ на файл.
- Фон: светлый нейтральный; ключевые элементы читаются и в тёмной теме GitHub.
- Палитра: navy `#082D5B`, cyan `#12C8F4`, amber `#FFAA16`, серый `#667085`.
- Стиль: строгая vector-like инфографика, крупные подписи, без 3D и фотостоков.
- Шрифт: Inter/Manrope или близкий гротеск; минимум 28 px после экспорта.
- Никаких декоративных карт, людей, экранов продукта или метрик, которых нет в коде.
- После генерации проверить весь текст вручную. Если генератор искажает буквы,
  создать изображение без текста и наложить подписи в Figma/Canva отдельным слоем.

## 1. Три слоя AKIM

**Файл:** `assets/architecture-overview.png`

**Место в README:** раздел «Архитектура», сразу после первого абзаца.

**Задача:** за пять секунд показать границы «Аким → Город ← Данные» и честно отделить
реализованное ядро от будущих UI/API/AI/V2.

**Композиция:** три крупные зоны слева направо. Слева — «Аким» с подписью «команды,
сравнение, объяснение» и статусом «план». В центре — «Город» с блоком `engine/v1`
и статусом «готово». Справа — «Данные» с блоком `data_gate` и статусом «готово».
Стрелка Data Gate → immutable snapshot → engine/v1 должна быть самой заметной.
Ответ движка возвращается к «Акиму» как Score, дельты и ошибки ограничений.

**Точные подписи:**

- `Аким · план`
- `Команды · сравнение · AI-объяснение`
- `Город · готово`
- `SimulationService`
- `Score · дельты · ошибки`
- `Данные · готово`
- `DataGateService`
- `Quality report · immutable snapshot · lineage`
- `HTTP API · план`

**Промпт для генерации:**

```text
Use case: infographic-diagram
Asset type: GitHub README architecture illustration
Primary request: clean three-layer architecture of AKIM city decision laboratory; left Governance layer is planned, center City V1 simulation layer is implemented, right Data Gate layer is implemented
Style/medium: precise flat vector-like engineering infographic
Composition/framing: 16:9 landscape; three large zones; strongest flow is Data Gate -> immutable snapshot -> V1 engine -> Score and deltas -> Governance; implemented paths solid, planned paths dashed
Color palette: deep navy, bright cyan, restrained amber accent, neutral light background
Constraints: large readable labels; no 3D; no UI mockup; no city skyline; no people; no watermark; no invented components
```

## 2. Расчёт V1

**Файл:** `assets/v1-calculation-pipeline.png`

**Место в README:** раздел «Как считается V1» перед формулами.

**Задача:** показать точный детерминированный путь от пяти решений до результата.

**Композиция:** горизонтальный pipeline из шести шагов. Под валидатором — красная
ветка `ошибки → score: null`. Под расчётом — три небольших блока декомпозиции:
`0.7 × среднее`, `0.3 × минимум`, `− критические значения`.

**Точные подписи:**

1. `5 решений`
2. `Валидация`
3. `Эффекты × (8 − лаг) / 8`
4. `Синергии → clip 0…100`
5. `Оценки районов`
6. `Score + декомпозиция`
7. `Невалидно → score: null`

**Промпт для генерации:**

```text
Use case: scientific-educational
Asset type: deterministic calculation pipeline for a GitHub README
Primary request: explain the AKIM V1 calculation from exactly five policy selections through validation, lag-scaled effects, synergies, clipping, district scores, and final decomposition
Style/medium: flat technical diagram with six numbered stages and one explicit invalid branch
Composition/framing: 16:9 horizontal flow; invalid branch goes downward to score null; final stage splits into average, minimum, and critical penalty components
Color palette: navy for calculation, cyan for valid flow, amber for result, muted red only for invalid flow
Constraints: formulas must stay legible; no decorative city art; no 3D; no watermark; no extra stages
```

## 3. Data Gate

**Файл:** `assets/data-gate-pipeline.png`

**Место в README:** раздел «Data Gate» перед таблицей форматов.

**Задача:** показать, почему исходный файл не попадает в симуляцию напрямую.

**Композиция:** слева три источника (`source text`, `City JSON`, `GeoJSON`), затем
единый pipeline. В quality report две ветки: critical блокирует публикацию; warning
требует явного принятия. Справа immutable snapshot с checksum и стрелкой в engine/v1.

**Точные подписи:**

- `Источники`
- `Raw · checksum`
- `Parser · mapping`
- `Quality report`
- `Preview изменений`
- `Publish`
- `Immutable snapshot`
- `Lineage · rollback`
- `Critical → блокировка`
- `Warning → явное принятие`
- `engine/v1`

**Промпт для генерации:**

```text
Use case: infographic-diagram
Asset type: Data Gate pipeline for a technical GitHub README
Primary request: show three source adapters converging into raw checksum storage, parser and mapping, quality report, change preview, publish, immutable snapshot with lineage and rollback, then V1 engine
Style/medium: clean flat vector-like data pipeline infographic
Composition/framing: 16:9 left-to-right flow; critical quality issues visibly block publish; warnings require explicit acceptance; snapshot is shown as immutable and versioned
Color palette: deep navy and cyan, amber for warning, muted red for blocking errors, light neutral background
Constraints: no database claims; no cloud services; no 3D; no people; no watermark; no invented file formats
```

## 4. Целевая динамика V2

**Файл:** `assets/v2-target-architecture.png`

**Место в README:** раздел «Что дальше», горизонт «Следующий шаг — квартал».

**Статус на изображении:** крупная подпись `ЦЕЛЕВАЯ АРХИТЕКТУРА · ЕЩЁ НЕ РЕАЛИЗОВАНО`.

**Задача:** показать направление развития, не выдавая V2 за готовую функцию.

**Композиция:** в центре event scheduler и глобальные модельные часы. Вокруг пять
модулей: транспорт, среда, социальная инфраструктура, безопасность, городской сервис.
Снизу — ledger, event log, checkpoint/replay. Справа — ветка baseline и ветка решения
акима из одного checkpoint. Три масштаба времени отмечены отдельной легендой.

**Точные подписи:**

- `ЦЕЛЕВАЯ АРХИТЕКТУРА · ЕЩЁ НЕ РЕАЛИЗОВАНО`
- `Scheduler · модельное время`
- `Оперативный · 5–15 минут`
- `Суточный · день`
- `Стратегический · месяц`
- `Транспорт`
- `Среда`
- `Социальная инфраструктура`
- `Безопасность`
- `Городской сервис`
- `Ledger`
- `Event log`
- `Checkpoint · replay`
- `Baseline`
- `Решение акима`

**Промпт для генерации:**

```text
Use case: infographic-diagram
Asset type: target V2 architecture roadmap illustration
Primary request: clearly marked future architecture for an event-driven city simulation with a central scheduler, three time scales, five city modules, ledger, event log, checkpoints, replay, and two branches from one checkpoint
Style/medium: rigorous flat systems architecture infographic
Composition/framing: 16:9; central scheduler with modules around it; persistence below; baseline and intervention branches to the right; a prominent top banner states that this architecture is not implemented yet
Color palette: subdued navy and gray for planned components, cyan for flows, amber for intervention branch
Constraints: everything shown as planned/dashed; no claim of live city data; no agents drawn as crowds; no 3D; no watermark
```

## Чеклист перед вставкой

- Все подписи совпадают с этим файлом и не содержат искажённых букв.
- Реализованное и запланированное визуально различаются без чтения мелкого текста.
- Ни одна схема не обещает HTTP API, UI, AI или V2 как готовые функции.
- Alt-текст описывает смысл схемы, а не повторяет имя файла.
- Изображение читается при ширине 900 px и весит меньше 2 МБ.
- После добавления файла ссылка в README относительная: `assets/<name>.png`.
