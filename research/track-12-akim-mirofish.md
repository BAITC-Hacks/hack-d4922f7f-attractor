# Трек 12 «Аким на 5 часов»: исследование MiroFish и дизайн узкого MVP

> [!WARNING]
> **Архивный вариант.** Команда решила не использовать MiroFish как зависимость. Актуальный дизайн сохраняет multi-agent подход, но реализует собственный AI-совет жителей: [track-12-akim-agent-simulation.md](./track-12-akim-agent-simulation.md).

> Дата проверки источников: 23 сентября 2026 года.  
> Режим: быстрый хакатонный research по первичным источникам.  
> Статус: аналитическая рекомендация, не спецификация реальной городской системы.

## Решение в одном абзаце

**Трек стоит брать, если команда отделит проверяемую математику от эффектного AI-слоя.** Итоговый `Astana Quality of Life Score` должен считаться локально, мгновенно и детерминированно из пяти решений, бюджета и явных коэффициентов. MiroFish следует использовать только как опциональную симуляцию реакции пяти групп жителей и поиска вторичных рисков: кто выиграл, кто проиграл, где возникнет сопротивление. Это соответствует его реальному устройству — документы → онтология/граф → персоны → социальная multi-agent simulation → отчёт — но не приписывает языковым агентам способность достоверно прогнозировать инженерные KPI ([официальный README](https://github.com/666ghj/MiroFish/blob/main/README.md#-workflow)). Для пятичасового хакатона полная интеграция upstream MiroFish — высокий риск: нужны отдельные LLM- и Zep-ключи, Python 3.11–3.12, Node 18+, облачный граф, много LLM-вызовов и асинхронный pipeline ([README: prerequisites и keys](https://github.com/666ghj/MiroFish/blob/main/README.md#-quick-start), [.env.example](https://github.com/666ghj/MiroFish/blob/main/.env.example)).

> [!IMPORTANT]
> После первого исследования организаторы предоставили точный датасет: 5 районов, 10 показателей, 14 мер, лаги, синергии, конфликты и официальную формулу Score. Он заменяет иллюстративную трёхрайонную модель и собственную формулу, предложенные ниже в разделах 5–7. Для реализации использовать только официальный расчёт; подробная проверка — в [аудите датасета](./track-12-dataset-audit.md).

## 1. Что обязательно в кейсе

По исходному [треку 12](../../tracks/track-12.md) продукт обязан:

1. дать всем одинаковый виртуальный бюджет и исходные данные;
2. позволить принять решения по пяти направлениям: транспорт, озеленение, социальная инфраструктура, безопасность, городской сервис;
3. не позволить превысить бюджет;
4. менять показатели при изменении решений;
5. считать итоговый `Astana Quality of Life Score`;
6. дать понятное AI-объяснение сильных сторон, рисков и компромиссов.

Синтетический датасет прямо разрешён. Значит, реальная статистика нужна для правдоподобной калибровки и storytelling, но не должна блокировать разработку.

Хакатон оценивает соответствие и работоспособность, техническую реализацию и README/воспроизводимость по 25 баллов каждый; ценность — 15, оригинальность — 10. Поэтому стабильный happy path и прозрачная формула важнее тяжёлой симуляции. Правила участия дополнительно требуют, чтобы проект был создан во время хакатона и каждый участник внёс личный вклад; готовый MiroFish допустим как зависимость, но не может быть предъявлен как собственная разработка команды ([локальная выписка из официальных правил](../../docs/01-pravila-zacheta.md)).

## 2. MiroFish: что это на самом деле

### 2.1 Назначение и архитектура

Официальный upstream — [666ghj/MiroFish](https://github.com/666ghj/MiroFish). Авторы описывают его как swarm-intelligence prediction engine: он извлекает сущности и отношения из загруженных материалов, строит «параллельный мир», создаёт агентов с персонами и памятью, запускает взаимодействие на двух социальных платформах, затем формирует отчёт и позволяет общаться с агентами ([README, overview и workflow](https://github.com/666ghj/MiroFish/blob/main/README.md#-overview)). Движок симуляции основан на [CAMEL-AI OASIS](https://github.com/camel-ai/oasis); backend-зависимости фиксируют `camel-oasis==0.2.5`, `camel-ai==0.2.78`, Flask, OpenAI-compatible client и `zep-cloud==3.25.0` ([backend/pyproject.toml](https://github.com/666ghj/MiroFish/blob/main/backend/pyproject.toml)).

Фактический pipeline:

```text
policy seed (.md/.txt/.pdf)
  → LLM генерирует ontology
  → Zep Cloud строит knowledge graph
  → MiroFish генерирует personas/config
  → OASIS имитирует Twitter/Reddit-взаимодействия
  → ReportAgent анализирует журнал и граф
  → narrative report
```

Backend — Flask-сервис с CORS и тремя группами маршрутов: `/api/graph`, `/api/simulation`, `/api/report`; health-check — `/health` ([app factory](https://github.com/666ghj/MiroFish/blob/main/backend/app/__init__.py#L39-L71)). В коде есть REST-маршруты для загрузки документов и генерации онтологии, асинхронного построения графа, запуска/контроля симуляции и отчётов. Например, `POST /api/graph/ontology/generate` принимает PDF/MD/TXT и simulation requirement, а `POST /api/graph/build` запускает фоновую сборку Zep-графа ([graph API source](https://github.com/666ghj/MiroFish/blob/main/backend/app/api/graph.py#L242-L449)).

### 2.2 Установка, ключи и интерфейс

Официально поддержаны два пути:

- source: Node.js 18+, Python ≥3.11 и ≤3.12, `uv`, затем `npm run setup:all` и `npm run dev`;
- Docker: `docker compose up -d`, frontend на `3000`, backend на `5001` ([официальный Quick Start](https://github.com/666ghj/MiroFish/blob/main/README.md#-quick-start), [docker-compose.yml](https://github.com/666ghj/MiroFish/blob/main/docker-compose.yml)).

Обязательные секреты upstream:

- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME`; API должен быть совместим с OpenAI SDK;
- `ZEP_API_KEY` для memory/knowledge graph;
- отдельный boost-LLM опционален ([.env.example](https://github.com/666ghj/MiroFish/blob/main/.env.example)).

Официальный README рекомендует Qwen Plus и предупреждает о высоком расходе, предлагая начать менее чем с 40 раундов ([README](https://github.com/666ghj/MiroFish/blob/main/README.md#1-configure-environment-variables)). Отдельного стабильного публичного SDK или CLI-контракта upstream README не документирует; документированы web UI и внутренние Flask endpoints. **UNVERIFIED:** обратная совместимость этих endpoints между коммитами не обещана.

### 2.3 Latency и ресурсы

- Graph build асинхронен: backend создаёт задачу, режет текст на chunks, отправляет batch в Zep, ждёт cloud processing и лишь потом получает граф ([исходник graph build](https://github.com/666ghj/MiroFish/blob/main/backend/app/api/graph.py#L602-L735)).
- Симуляция делает много LLM-вызовов; сам проект предупреждает о высоком расходе и рекомендует <40 раундов ([.env.example](https://github.com/666ghj/MiroFish/blob/main/.env.example)).
- **UNVERIFIED:** upstream не публикует официальный benchmark wall-clock latency, token cost, RAM/CPU/GPU для типового запуска.
- **UNVERIFIED:** запуск полного pipeline за время live demo нельзя гарантировать без предварительного rehearsal на тех же ключах, модели, сети и seed.
- Локальная GPU в заявленных prerequisites отсутствует; основная неопределённость — внешние LLM/Zep, а не GPU ([README prerequisites](https://github.com/666ghj/MiroFish/blob/main/README.md#prerequisites)).

### 2.4 Лицензия

Репозиторий лицензирован под **GNU AGPL-3.0** ([LICENSE](https://github.com/666ghj/MiroFish/blob/main/LICENSE)). Если команда модифицирует MiroFish и предоставляет пользователям доступ к изменённой версии по сети, AGPL предусматривает предоставление corresponding source пользователям сервиса; для хакатонного репозитория безопаснее держать MiroFish отдельным сервисом/не модифицировать его и сохранить copyright/license notices. Это не юридическая консультация.

## 3. Где MiroFish полезен, а где опасен

### Полезен

1. **Stakeholder stress-test.** Превратить пять сухих бюджетных решений в реакции групп: автомобилисты, пассажиры ОТ, семьи с детьми, жители периферии, предприниматели/городские службы.
2. **Вторичные эффекты.** Подсветить компромиссы, не входящие напрямую в score: недовольство района, perceived unfairness, конфликт краткосрочного ремонта с долгосрочной пользой.
3. **Эффектное demo.** После мгновенного расчёта показать «совет города»: 5 карточек мнений, 3 emergent risks, 1 рекомендацию перераспределения.
4. **Оригинальность.** Agentic-слой связан с задачей, если агенты получают фактический before/after state и не подменяют математику.

### Опасен или избыточен

1. **Не рассчитывает физические эффекты.** Социальная симуляция Twitter/Reddit не является транспортной, экологической или эпидемиологической моделью ([официальный workflow](https://github.com/666ghj/MiroFish/blob/main/README.md#-workflow)).
2. **Недетерминирован.** LLM-ответ и поведение агентов могут меняться; критерий «смена решений → смена score» должен доказываться без него.
3. **Слабая валидность персон.** Синтетические personas без опросов населения показывают правдоподобные нарративы, а не репрезентативное общественное мнение. Официальный FAQ требует трактовать результаты как симулированные гипотезы, а не эмпирические факты или причинные доказательства ([FAQ проекта, Q1 и Q5](https://github.com/666ghj/MiroFish/issues/726)).
4. **Зависит от двух облаков и ключей.** Отказ LLM или Zep ломает полный pipeline.
5. **Плохо помещается в 5 часов.** Развёртывание, изучение API, подготовка seed, graph build, personas, rounds и report конкурируют за время с обязательным продуктом.

**Вердикт:** MiroFish — `Should have`, никогда не `Must have` и никогда не источник QoL Score.

## 4. Первичные данные для правдоподобной Астаны

Для MVP достаточно синтетических районов, но их baseline и interventions стоит привязать к официальным метрикам.

| Домен | Что взять в синтетический датасет | Первичный ориентир |
|---|---|---|
| Транспорт | congestion/load 0–100, доступность ОТ, среднее время поездки | Бюро нацстатистики публикует пассажирооборот по регионам; для Астаны доступна региональная статистика и временные ряды ([регион Астана](https://stat.gov.kz/ru/region/astana/), [транспорт 2025](https://stat.gov.kz/ru/industries/businessstatistics/stat-transport/publications/472263/)). Показатель SDG 11.2 задаёт безопасный, доступный и устойчивый транспорт как целевую рамку ([БНС, Goal 11](https://stat.gov.kz/en/sustainable-development-goals/goal/11/)). |
| Озеленение/экология | green-access 0–100, деревья или площадь зелени на район, air burden | Акимат сообщает о 2,9 млн зелёных насаждений внутри города, 14,6 млн в зелёном поясе, 92 га ботсада, 9 парках/396 га, 90 скверах/132 га ([экологическая политика Астаны](https://www.gov.kz/memleket/entities/astana-upr/press/article/details/201674)). SDG 11.6 включает качество воздуха и отходы ([БНС, Goal 11](https://stat.gov.kz/en/sustainable-development-goals/goal/11/)). |
| Социальная инфраструктура | доступность школ/клиник, дефицит мест, coverage | В 2025 году город планировал открыть 15 школ на 22 912 мест, распределённых неравномерно по районам ([официальный акимат](https://www.gov.kz/memleket/entities/astana/press/news/details/930857?lang=ru)). Это подходит как сюжет дефицита, но не как полный районный dataset. |
| Безопасность | incidents per 1k, субъективная безопасность, response readiness | БНС приводит 16 045 зарегистрированных преступлений в Астане за 2025 год и публикует выгрузки/динамику доверия и чувства безопасности ([официальная статистика](https://stat.gov.kz/ru/industries/social-statistics/stat-crime/publications/473771/)). Нельзя сравнивать районы по абсолютным числам без населения и структуры регистрации. |
| Городской сервис | обращения/1k, SLA, first-contact resolution | iKOMEK109 принял 2 326 000 обращений в 2024 году; 98% переданных профильным организациям обращений обработаны в срок, цель first-call resolution — 85% ([официальный акимат](https://www.gov.kz/memleket/entities/astana/press/news/details/942726?lang=ru)). |

Для общего результата можно показать внешний benchmark, но не смешивать его с игровой формулой: БНС определяет качество жизни как междисциплинарное понятие и публикует субъективную удовлетворённость жизнью и услугами ([Quality of Life 2024](https://stat.gov.kz/en/industries/laborandincome/stat-life/publications/183426/)).

### Ограничения данных

- Перечисленные наборы имеют разные периоды, единицы, гранулярность и определения.
- Публикации уровня города не дают готовой причинной функции «X тенге → Y пунктов QoL».
- **UNVERIFIED:** доступность стабильного API с районной детализацией для всех пяти доменов.
- **UNVERIFIED:** возможность законно и быстро извлечь районные метрики из внутренних систем iKOMEK/CTS; на них MVP рассчитывать не должен.
- Абсолютное количество преступлений или обращений не равно риску/качеству без нормировки на население и propensity to report.

## 5. Методология QoL Score

UN-Habitat рассматривает городское благополучие как многомерную конструкцию: инфраструктура, качество жизни, equity/social inclusion, environmental sustainability, governance и productivity ([City Prosperity Index methodology](https://unhabitat.org/sites/default/files/2019/02/CPI-METADATA.2016.pdf)); его Global Urban Monitoring Framework специально согласует разные городские индексы и подчёркивает disaggregation и исключённые группы ([UMF](https://unhabitat.org/the-global-urban-monitoring-framework)).

OECD/JRC рекомендуют для composite indicators явно описывать теоретическую рамку, нормализацию, веса и aggregation; веса являются ценностным суждением, а equal weighting всё равно является выбором веса ([официальный Handbook](https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html)).

Отсюда дизайн игрового индекса:

```text
domain_score[district, domain] ∈ [0, 100]

delta = base_effect(intervention)
      × need_multiplier(district, domain)
      × diminishing_return(current_score)
      × synergy_or_tradeoff(selected_set)

district_qol = Σ_domain weight[domain] × resulting_domain_score
city_qol     = Σ_district population_share × district_qol
equity_penalty = λ × stdev(district_qol)

Astana_QoL = clamp(city_qol - equity_penalty, 0, 100)
```

Для демо:

- веса доменов равные: по 20%;
- `need_multiplier = 1 + (100 - baseline)/200`;
- diminishing returns: эффект × `(1 - baseline/140)`;
- 3–5 вручную заданных синергий, например автобусная полоса + умные светофоры `+2 transport`, парк + освещение `+1 green, +1 safety`;
- trade-off: новая магистраль `+transport`, но `-green` и временный `-service`;
- equity penalty показывает, почему инвестиции только в сильный район не максимизируют общий результат.

Коэффициенты — **игровые допущения, не прогноз реального эффекта**. Их нужно открыть в UI/README и хранить в versioned JSON. Один и тот же input + seed обязан давать идентичный score.

## 6. Архитектура узкого MVP

```text
Browser UI
  ├─ Scenario Store: districts.json + interventions.json
  ├─ Budget Guard: сумма выбранного ≤ 100 ед.
  ├─ Deterministic Scoring Engine
  │    ├─ 5 domain scores × 3 synthetic districts
  │    ├─ synergies / trade-offs
  │    └─ equity penalty + audit trace
  ├─ Explainability Renderer (template, always available)
  └─ Agent Adapter (optional)
       ├─ live MiroFish result if READY
       ├─ cached rehearsal artifact
       └─ deterministic persona fallback
```

### Must have

- один сценарий, три условных района, бюджет 100;
- 15 инициатив: по 3 на домен, каждая с ценой и явными эффектами;
- ровно по одному решению в каждом из пяти доменов;
- блокировка перерасхода до запуска;
- before/after radar или пять progress bars;
- итоговый QoL, изменение по районам и audit trail «почему +7.4»;
- объяснение из шаблонов + опциональная LLM-переформулировка;
- кнопка `Сбросить` и два preset-сценария для сравнения.

### Should have

- 5 карточек реакций stakeholder personas;
- MiroFish/cached simulation badge с честным статусом источника;
- рекомендация swap одной инициативы с пересчётом;
- неожиданный event после первого расчёта: снегопад / рост обращений / ремонт моста.

### Cut first

- full MiroFish UI и knowledge-graph visualisation;
- живой graph build во время демо;
- тысячи агентов и десятки раундов;
- real-time городские API;
- auth, leaderboard, multiplayer;
- карта с настоящей GIS-геометрией;
- генерация презентации.

## 7. Схема данных

```json
{
  "scenarioVersion": "astana-demo-v1",
  "budget": 100,
  "districts": [
    {
      "id": "saryarka-north",
      "name": "Сарыарка-Север (условный)",
      "populationShare": 0.34,
      "metrics": {
        "transport": 42,
        "green": 48,
        "social": 61,
        "safety": 55,
        "service": 50
      }
    }
  ],
  "interventions": [
    {
      "id": "bus-priority",
      "domain": "transport",
      "name": "Приоритет автобусов на 3 коридорах",
      "cost": 24,
      "targets": ["saryarka-north"],
      "effects": {"transport": 11, "service": -1},
      "rationale": "Игровое допущение v1",
      "stakeholders": ["transit_rider", "driver", "business"]
    }
  ],
  "synergies": [
    {"requires": ["pocket-park", "smart-lighting"], "effects": {"green": 2, "safety": 2}}
  ]
}
```

Результат хранит `inputHash`, `scoreVersion`, budget, selected IDs, before/after, каждое слагаемое score, equity penalty и `simulationStatus`. Это делает демо проверяемым и позволяет сравнить команды.

## 8. Как подключать MiroFish

### Безопасный вариант для хакатона

1. Отдельно подготовить `policy-seed.md`: baseline трёх районов, пять выбранных мер, их рассчитанные эффекты, stakeholder definitions и предупреждение, что данные синтетические.
2. До демо один раз прогнать MiroFish на малом числе агентов/раундов.
3. Преобразовать отчёт в собственный компактный JSON: `persona`, `support`, `concern`, `affectedDistrict`, `confidenceLabel`, `evidenceFromScenario`.
4. В UI использовать adapter: если live result готов за ограниченный timeout — показать его; иначе автоматически открыть cached artifact с пометкой `предварительно рассчитанная репетиция`.
5. Score никогда не менять результатом агентов. Агенты могут предложить swap, но новый score рассчитывает только deterministic engine.

### Контракт agent layer

```json
{
  "runId": "demo-balanced-v1",
  "source": "mirofish-live|mirofish-cached|local-fallback",
  "scenarioHash": "sha256:...",
  "personas": [
    {
      "id": "parent-periphery",
      "stance": -1,
      "concern": "Новая школа улучшает доступность не в нашем районе",
      "linkedMetrics": ["social", "equity"]
    }
  ],
  "emergentRisks": [],
  "suggestedSwap": {"remove": "...", "add": "..."}
}
```

**Не показывать** LLM chain-of-thought. Показывать краткие выводы и связь с входными метриками.

## 9. Happy path демонстрации (3 минуты)

1. «У всех одинаковая Астана: три условных района, QoL 51.8, бюджет 100».
2. Выбрать по одной инициативе в пяти доменах. При попытке дорогой комбинации интерфейс блокирует перерасход.
3. Нажать `Смоделировать`: через <1 секунды показать QoL `51.8 → 60.4`, остаток бюджета, пять domain deltas и районное неравенство.
4. Открыть `Почему`: каждая дельта разложена на baseline, intervention, diminishing return, synergy и equity penalty.
5. Открыть `Совет жителей`: пять MiroFish/cached persona reactions и риск «периферийный район почти не получил выгоды».
6. Принять предложенный swap. Детерминированно пересчитать `60.4 → 62.1`, показать меньшее неравенство.
7. Сравнить с preset `Только центр`: тот может иметь высокий средний эффект, но проиграть из-за equity penalty.

Финальная фраза: **«AI не выдумывает городской балл: формула проверяема; агенты помогают увидеть человеческие последствия, которые формула могла пропустить».**

## 10. План на 5 часов

| Время | Результат |
|---|---|
| 00:00–01:00 | Зафиксировать schema/formula; создать 3 района, 15 мер, budget guard; вручную проверить 3 сценария. Параллельно один человек проверяет запуск MiroFish и ключи, не блокируя продукт. |
| 01:00–02:00 | Один экран выбора, счётчик бюджета, мгновенный score, before/after. |
| 02:00–03:00 | Explainability/audit trace, equity penalty, 2 presets, unit tests formula и over-budget. |
| 03:00–04:00 | Persona panel. Если MiroFish уже дал стабильный artifact — adapter; иначе fallback. Полировка demo states. |
| 04:00–04:30 | End-to-end rehearsal на чистом запуске, README с командами и допущениями, скриншоты. |
| 04:30–05:00 | Только исправление блокеров, запись backup video/GIF, повторный demo два раза. Никаких новых функций. |

### Первые 60 минут поминутно

- 0–10: назначить владельцев UI, score/data, AI integration, README/demo; записать Definition of Done.
- 10–20: утвердить budget=100, 3 района, 5×3 interventions, equal domain weights, equity penalty.
- 20–35: score owner реализует pure function + 4 теста: baseline, over-budget, changed selection, deterministic replay.
- 20–35 параллельно: UI owner собирает один экран на mock JSON.
- 20–35 параллельно: AI owner проверяет `docker compose`, версии, наличие LLM/Zep keys и запускает минимальный seed. **Stop rule:** через 15 минут без зелёного health/graph build перейти к cached/fallback.
- 35–50: соединить UI и scoring; проверить, что все пять направлений обязательны.
- 50–60: записать первый end-to-end screen capture. Если его нет — остановить MiroFish-работу и чинить core.

## 11. Fallback без MiroFish

Fallback сохраняет всю ценность кейса:

1. пять фиксированных stakeholder profiles в JSON;
2. rule-based reaction: persona получает weighted sum эффектов по важным ей доменам и району;
3. LLM одним вызовом переформулирует уже рассчитанные facts, но при ошибке отображается шаблон;
4. emergent risks выбираются из rule library по trade-offs и низкому equity;
5. UI честно пишет `локальная сценарная модель`, а не `MiroFish`.

```text
support(persona) = Σ preference[domain] × delta[persona.district, domain]
concerns = rules where threshold crossed
```

Такой слой детерминирован, мгновенен, воспроизводим без аккаунтов и демонстрирует agentic framing без ложной претензии на массовое прогнозирование.

## 12. Риски и неизвестные

| Риск | Вероятность / ущерб | Митигирование |
|---|---|---|
| MiroFish/Zep/LLM не поднялся | высокая / высокий | 15-минутный stop rule; cached artifact; fallback personas |
| Live run дольше demo | высокая / высокий | score синхронный; simulation async; timeout 5–8 секунд; заранее рассчитанный artifact |
| Жюри воспринимает score как выдумку | средняя / высокий | открыть формулу, coefficients JSON, audit trace, label «синтетическая модель» |
| LLM меняет цифры | средняя / высокий | передавать цифры как read-only facts; UI берёт числа только из scoring engine |
| Симуляция выглядит как пять чат-ботов | средняя / средний | разные utility functions, районы, конфликт интересов; показать агрегированный disagreement |
| Перерасход/API key leak | средняя / высокий | server-side secrets, limits, малые rounds, никаких ключей во frontend/repo |
| AGPL не учтена | низкая / средний | не копировать код в продукт без notices; держать отдельным сервисом; опубликовать изменения при сетевом использовании |
| Реальные данные несопоставимы | высокая / средний | synthetic baseline, ссылки на ориентиры, никаких причинных обещаний |
| «AI анализ» недоказуем | средняя / средний | демонстрировать structured persona output и fallback; не называть narrative score |

Открытые вопросы перед стартом:

- Есть ли гарантированные рабочие `LLM_API_KEY` и `ZEP_API_KEY`, разрешённые для командного демо?
- Разрешён ли внешний network во время разработки и показа?
- Какая машина и Docker доступны? **UNVERIFIED.**
- Сколько человек и кто уверенно делает frontend/backend? `team/skills.yaml` перечисляет инструменты, а не фактические навыки участников; соответствие команды этому стеку **UNVERIFIED**.
- Требуется ли судьям именно live MiroFish либо достаточно показать собственный agent layer, вдохновлённый его подходом?
- Можно ли заранее сохранить результат внешней симуляции в репозитории и честно обозначить его как cached run?

## 13. Итоговая продуктовая формулировка

**«Аким на 5 часов» — проверяемая бюджетная песочница: пользователь распределяет 100 единиц между пятью направлениями и сразу видит изменение качества жизни и неравенства трёх условных районов; совет AI-жителей затем выявляет общественные компромиссы и предлагает одно улучшение сценария.**

Короткая оценка:

- реализуемость core за 5 часов: **2/2**;
- live upstream MiroFish за 5 часов: **0–1/2**, зависит от готовых ключей и rehearsal;
- демо без личных аккаунтов: **2/2** только с fallback/cached layer, **0/2** для чистого upstream;
- проверяемость результата: **2/2** при детерминированном score;
- потенциал выделиться: **2/2**, если показать конфликт эффективности и справедливости, а не просто LLM-текст;
- интеграционный риск: **высокий** для полного MiroFish, **низкий/средний** для adapter architecture.

**Рекомендация:** делать продукт с MiroFish-compatible adapter и обязательным fallback. Интегрировать live MiroFish только после того, как весь основной demo уже работает и воспроизводится с выключенной сетью.

## 14. Дополнение после получения официального датасета

Датасет **существенно повышает перспективность трека** и снимает главный прежний риск — произвольность QoL Score. Контрольные числа воспроизводятся:

- оценки районов: Есиль `62.99`, Алматы `57.06`, Сарыарка `54.65`, Байконур `56.63`, Нура `49.18`;
- `D_avg = 56.8624`, два критических показателя в Нуре, базовый `Score = 52.55768`;
- опубликованный пример даёт `Score = 56.54307`, то есть заявленные `≈56.5` и `+4.0` корректны.

При буквальном переборе правил лучший найденный набор — `M2 + M3(Нура) + M8(Нура) + M9(Нура) + M14`, стоимость `98`, `Score = 57.236735`. Это выявляет не ошибку вычисления, а особенность дизайна: штраф `N_crit` создаёт резкий бонус при переходе через порог `40`, а компонент `0.3 × min(D_d)` делает инвестиции в Нуру более чем вдвое ценнее аналогичного районного эффекта в Есиле, пока Нура остаётся минимумом. Поэтому продукт обязан показывать отдельно `D_avg`, слабейший район, `N_crit` и вклад каждой меры — иначе пользователь не поймёт, откуда взялся выигрыш.

### Обновлённое решение по треку

- **Статус:** из «простого, но потенциально произвольного» трек переходит в **сильные финалисты**.
- **Ядро MVP:** буквальная реализация 5 районов, 10 показателей, 14 мер, лагов, трёх синергий, трёх несовместимостей, пяти уникальных решений и валидатора бюджета/направлений.
- **Главная продуктовая история:** эффективность против справедливости — математически лучший набор концентрирует помощь в слабом районе, а MiroFish показывает реакцию остальных групп.
- **Роль MiroFish не меняется:** он объясняет общественные последствия уже рассчитанного сценария, но не считает эффекты, Score, лаги или синергии.
- **Надёжный happy path:** deterministic engine → audit trail → cached MiroFish artifact с hash сценария → автоматический local fallback.

### Оценка по таблице жюри

Это не обещание результата, а диапазон при качественной реализации и коротком доказательном демо.

| Вариант | Соответствие /25 | Техника /25 | README /25 | Ценность /15 | Оригинальность /10 | Диапазон |
|---|---:|---:|---:|---:|---:|---:|
| Детерминированное ядро без MiroFish | 22–25 | 18–22 | 19–24 | 10–13 | 4–6 | **73–87** |
| Ядро + adapter + cached MiroFish + fallback | 22–25 | 20–24 | 20–24 | 11–14 | 7–9 | **82–94** |
| Live MiroFish падает, fallback отсутствует | 12–18 | 10–17 | 14–21 | 8–12 | 5–8 | **49–70** |

На демо для максимума нужно доказать: точное воспроизведение `52.55768` и `56.54307`; блокировку каждого невалидного набора; независимость результата от порядка решений; агрегирование эффектов до `clip`; объяснение порога `<40`; одну команду запуска без обязательных аккаунтов; честный badge `live / cached / fallback`; MiroFish-реакцию, привязанную к конкретному before/after, а не декоративный чат.

Полный разбор арифметики, exploit-механик, неоднозначностей спецификации и причин потери баллов находится в [отдельном аудите датасета](./track-12-dataset-audit.md).
