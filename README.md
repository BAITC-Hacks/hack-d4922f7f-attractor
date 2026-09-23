<div align="center">

<img src="assets/akim-logo.png" alt="Логотип AKIM" width="220" />

# AKIM

### Проверяемая лаборатория бюджетных решений для городского управления

`Python 3.11+` · `FastAPI` · `OpenAI Responses (опционально)` · `Clean Architecture`

[Запуск](#быстрый-старт) · [Демо](#демо-бэкенда) · [Архитектура](#архитектура) · [API](#api-first-контракты) · [Планы](#что-дальше)

</div>

> Городские решения конкурируют за один бюджет, а их эффект трудно проверить до
> запуска. AKIM рассчитывает **Astana Quality of Life Score (AQOL)** по условию
> «Аким на 5 часов» и показывает проверяемые причины изменения результата.

## Два режима

| | V1 · Задание хакатона | V2 · Исследовательская симуляция |
| --- | --- | --- |
| Вопрос | Как пять мер меняют заданный Score? | Как город развивается во времени при разных решениях? |
| Основа | 5 условных районов, 14 мер, бюджет 100 | Жители, инфраструктура, службы, городские финансы, внешняя экономика |
| Динамика | Итог по формуле с лагом | События, очереди, передвижения, проекты, сезонность |
| AI | Объясняет расчёт и исследует альтернативы | Помогает ставить эксперименты, общаться с агентами, анализировать процессы |
| Доказательство качества | Контрольные числа и тесты правил | Проверка механизмов, калибровка, исторические тесты, неопределённость |

V1 сохраняет исходные правила без изменений. V2 получает отдельные версии данных,
моделей и метрик. Модельные реакции жителей не меняют официальный Score V1.

## Текущий статус

Реализован **бэкенд V1**: API, evaluator, Data Gate, локальный поиск альтернатив,
отчёт с evidence. Фронтенд подключается отдельно; V2 остаётся планом.
LLM-адаптер проверен тестовыми ответами; живой вызов провайдера в этом прогоне
**не выполнялся**. Без ключа явно возвращается `mode: rule-based`.

| Возможность | Реализация | Доказательство |
| --- | --- | --- |
| Расчёт AQOL | Эффекты, лаги, синергии, clip, штрафы и декомпозиция | Контрольный Score **56.54307** |
| Проверка портфеля | Ровно 5 уникальных мер, бюджет ≤100, ≤2 мер одного направления, районы и конфликты | Невалидный набор получает `score: null` |
| Data Gate → API | Исходник → quality report → опубликованный snapshot → evaluator | V1 закреплён за одним снимком |
| Альтернативы | Перебор одной замены меры/района; фиксация решений | Найден вариант **57.20556** за **100** |
| Объяснение | Сильные стороны, риски, последствия и проверенные предложения | Числа и формулировки берутся из серверного evidence |
| API-first | OpenAPI, проверка версий, структурные ошибки | HTTP integration tests |

## Быстрый старт

Нужно: Python **3.11+**, доступ к PyPI для установки. БД и ключ LLM для demo не нужны.
Из корня клонированного [репозитория](https://github.com/BAITC-Hacks/hack-d4922f7f-attractor),
PowerShell:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -c requirements.lock ".[test]"
.venv/Scripts/python -m unittest discover -s tests -t .
.venv/Scripts/python -m uvicorn services.api.app:app --host 127.0.0.1 --port 8000
```

<details>
<summary>Linux / macOS</summary>

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements.lock ".[test]"
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python -m uvicorn services.api.app:app --host 127.0.0.1 --port 8000
```

</details>

[Swagger UI](http://127.0.0.1:8000/docs) · [Каталог](http://127.0.0.1:8000/catalog).
API сам импортирует и публикует официальный исходник. Хранилище:
`var/data-gate` относительно текущего каталога. Запускать **один worker**.

## Демо бэкенда

Во втором терминале, пока сервер запущен:

```powershell
.venv/Scripts/python -m scripts.demo_backend
```

Проверяются каталог/версии → контрольный расчёт → отказ неполному набору →
альтернативы → evidence-backed report. Сохранённый реальный HTTP-прогон:
[backend-demo.json](docs/evidence/backend-demo.json).

Для `POST /v1/evaluate` в Swagger:

```json
{
  "selections": [
    {"measureId": "M7", "districtId": "nura"},
    {"measureId": "M8", "districtId": "nura"},
    {"measureId": "M10", "districtId": "nura"},
    {"measureId": "M12", "districtId": null},
    {"measureId": "M5", "districtId": "saryarka"}
  ]
}
```

Результат: `valid: true`, `cost: 95`, `score: 56.54307`. `aqolScore` — алиас Score.
Для интеграции передавайте также `versions` целиком из `GET /catalog`.

## Архитектура

| Слой | Ответственность | Реализация |
| --- | --- | --- |
| Аким / API | HTTP, доступ к импорту, версии, сборка use cases | `services/api` |
| Город | Валидация, точный расчёт, локальные альтернативы | `engine/v1` |
| Данные | Парсеры, паспорт, quality gate, snapshots, lineage | `data_gate` |
| AI-аналитик | Выбор подтверждённых фактов, read-only tools, fallback | `ai` |

Домен/application движка не импортируют FastAPI, OpenAI SDK или Data Gate.
Composition root `services/api/runtime.py` переводит опубликованный payload в
immutable модель. Пользовательские импорты не подменяют официальный V1.
`create_official_service()` оставлен как загрузчик эталонного fixture.

Брифы для будущих изображений: [README-VISUALS.md](docs/README-VISUALS.md).
Целевая архитектура с V2: [docs/02-architecture.md](docs/02-architecture.md).

## Как считается V1

```text
I′ = clip(I + Σ effect × (8 − lag) / 8 + synergy, 0, 100)
Ddistrict = Σ weight × I′
Score = 0.7 × Davg + 0.3 × min(Ddistrict) − Ncritical
```

Нужно **ровно пять мер, не больше двух одного направления**, а не по одной каждой
категории. Промежуточные значения не округляются. Критичность — строго ниже 40;
остаток бюджета бонуса не даёт. LLM не считает Score.
[Полная спецификация](docs/03-v1-reference-model.md).

## Проверенные результаты

Локально: Windows, Python 3.12.10. CI для Python 3.11/3.12 добавлен; удалённый
результат CI пока не подтверждён.

| Проверка | Результат |
| --- | --- |
| Автотесты | **102 проходят**: engine, Data Gate, HTTP, search, AI policy |
| База без мер (диагностика) | **52.55768** |
| Контрольный портфель за 95 | **56.54307** |
| Декомпозиция прироста | **+0.85064 +1.13475 +2 = +3.98539** |
| Лучшая найденная локальная альтернатива | **57.20556**, стоимость **100** |
| Официальный импорт | **0 critical / 0 warning** |
| Установка | `pip install`, сборка wheel, ресурсы и HTTP smoke вне checkout |
| Статические проверки | Ruff, `pip check`, синхронизация OpenAPI |

## API-first контракты

| Endpoint | Назначение |
| --- | --- |
| `GET /health`, `GET /catalog` | Готовность, каталог, правила, версии, manifest |
| `POST /v1/validate` | Валидация без LLM |
| `POST /v1/evaluate` | Расчёт; неправильный портфель → 200 с `valid: false` |
| `POST /v1/alternatives` | Одна замена; `fixedSelections`, `allowedDistricts`, `resultLimit` |
| `POST /v1/analysis` | Отчёт с evidence, явными `mode` и статусом fallback |
| `POST /datasets/imports` | Текстовый импорт с паспортом; admin token |
| `GET /datasets/imports/{id}/report` | Report, mapping, preview; admin token |
| `POST /datasets/imports/{id}/publish` | Публикация с принятием warnings; admin token |
| `GET /datasets` | Наборы и manifest; admin token |

Неверная структура → 422; устаревшие версии / запрещённая публикация → 409;
нет доступа → 403; body >1 200 000 байт → 413.
Ошибки: `error: {code, field, message}`.
[Контракты и расхождения с черновым frontend-клиентом](packages/contracts/README.md).

## AI и конфигурация

LLM выбирает/упорядочивает готовые evidence IDs. Сервер проверяет категорию,
обязательные риски и полноту, затем подставляет собственные числа и фразы.
Это ограниченный evidence-аналитик, не свободный городской агент.
Невалидный ответ: один repair, затем шаблон. Ошибка провайдера не ломает расчёт.

| Переменная | Назначение |
| --- | --- |
| `AKIM_DATA_GATE_DIR` | Путь хранилища |
| `AKIM_CORS_ORIGINS` | Разрешённые адреса UI через запятую; по умолчанию закрыто |
| `AKIM_ADMIN_TOKEN` | Bearer token для Data Gate; без него HTTP-доступ закрыт |
| `AKIM_LLM_ENABLED=1` | Явное включение платных запросов |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Ключ и доступная Responses-модель с tools/structured outputs |
| `AKIM_LLM_MAX_ANALYSES` | Анализов на процесс: по умолчанию 10, максимум 100 |

[.env.example](.env.example) — пример, **не загружается автоматически**. Экспортируйте
переменные в окружение процесса. Ключи не коммитьте. Лимиты LLM: один одновременный
анализ, deadline 20 секунд, ≤3 вызовов включая repair, ≤800 output tokens/вызов;
SDK retries отключены. Это не денежный лимит: настройте бюджет проекта провайдера.

## Data Gate

Поддержаны исходник задания, City JSON, GeoJSON WGS84. Дубли JSON-ключей,
NaN/Infinity, неверные типы/даты/ссылки не исправляются молча. Критические ошибки
блокируют публикацию; checksum staging и snapshot проверяется при чтении.
Идентичность импорта учитывает байты, формат, паспорт и transform version.

```powershell
.venv/Scripts/python -m data_gate --store var/data-gate bootstrap
```

[CLI и правила миграции](data_gate/README.md).

## Структура проекта

```text
engine/v1/          правила, evaluator, application service, локальный search
data_gate/          import, quality, snapshots, файловые/in-memory adapters, CLI
services/api/       HTTP-модели, маршруты, доступ, composition root
ai/                 evidence policy и Responses adapter
packages/contracts/ domain JSON Schema и генерируемый OpenAPI
data/               исходник и эталонный fixture (входят в wheel)
tests/              golden, regression, integration, search, AI contract tests
scripts/            HTTP demo, OpenAPI export, wheel smoke
docs/               спецификации, аудит, evidence
assets/             логотип и будущие изображения README
```

## Что дальше

**Перед защитой:** согласовать UI-контракт, записать демо, проверить живую LLM-модель
и сравнить пользу с rule-based baseline, получить зелёный CI. Сроки не зафиксированы.

**Следующий этап:** транзакционный PostgreSQL-адаптер, роли, наблюдаемость и замеры
нагрузки; затем отдельный V2 scheduler, ledger, replay по [плану](docs/08-delivery-plan.md).

**Дальше:** реальные разрешённые данные, калибровка/holdout, новые `SourceParser`
adapters и ансамбли V2. Масштабирование обосновывается измерениями.

## Ограничения

- V1 — синтетическое задание, не прогноз и не доказательство причинного эффекта.
- Поиск локальный: глобальный максимум не заявляется.
- Live LLM, UI, пользовательские исследования и V2 не подтверждены этим прогоном.
- Файловый Data Gate: один процесс-писатель; не запускайте CLI/API одновременно
  на одном хранилище. Lock API не заменяет межпроцессные транзакции.
- Нет готового публичного production deployment, RBAC, постоянного бюджета LLM,
  нагрузочного отчёта или проверенного контейнерного запуска.
- Отдельная лицензия, состав команды и видео защиты пока не опубликованы.

## Документация

[Продукт](docs/01-product.md) · [Архитектура](docs/02-architecture.md) ·
[V1](docs/03-v1-reference-model.md) · [V2](docs/04-v2-simulation.md) ·
[Данные](docs/05-data-gate.md) · [AI](docs/06-ai-and-interactions.md) ·
[Исследования](docs/07-research-validation.md) · [План](docs/08-delivery-plan.md).

Оценка по обеим рубрикам, исправления и приоритеты:
[BACKEND-AUDIT.md](docs/BACKEND-AUDIT.md).

Данные предоставлены в [условии задачи](data/source-dataset.ru.txt).
«Исследовательская платформа» означает воспроизводимые гипотезы и прозрачные
допущения, а не подтверждённую точность на реальном городе.
