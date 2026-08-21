# agent-forge

Управляемая последовательная LLM-кодогенерация поверх любого OpenAI-совместимого API: очередь задач от спецификации, реальные тестовые гейты, ревью второй моделью, жёсткие бюджетные капы и полный журнал на диске. English version: [README.md](README.md).

## Зачем

Прогнать «напиши мне фичу» через LLM — легко. Прогнать *десятки* таких задач по реальному репозиторию, не теряя контроль, — нет. agent-forge делает серийную кодогенерацию управляемой:

- **Гейты из тестов, а не доверие.** У каждой задачи есть `acceptance`-команды (реальные тесты/линтеры), которые обязаны завершиться с кодом 0 — иначе задача не считается сделанной.
- **Вторая модель проверяет первую.** Роль reviewer (другая, более дешёвая модель) должна одобрить результат; провалы уходят в ограниченный repair-цикл (≤3 итераций), а не в тихий merge.
- **Бюджетные капы в USD.** Лимиты per-task, per-run и per-day; превышение переводит задачу в `blocked` с причиной в журнале — никаких runaway-счетов.
- **DISPUTE вместо галлюцинаций.** Если repair-агент не может согласовать спеку с реальностью, он поднимает маркеры `DISPUTE`/`STUCK`, и задача останавливается явно — инструмент никогда не заметает противоречия под ковёр.
- **Всё на диске.** Каждый прогон — обычный каталог `runs/<run_id>/` (журнал + состояния задач); процесс можно убить в любой момент, и `forge resume` продолжит со снапшотов истории.
- **YAML писать не обязательно.** `forge init` и `forge wizard` сами сканируют целевой проект, находят его реальные проверки и чертят всю настройку — задачи, acceptance, бюджеты — а вы только подтверждаете.

## Возможности

- **Онбординг для проекта в любом состоянии** — от пустой папки до легаси-монорепы:
  - `forge init` — определяет стек (Python/Node/.NET), инициализирует git при необходимости, пишет skeleton `tasks.yaml` с реально найденными проверками, прогоняет baseline (красный baseline — честный стоп до любого вызова модели).
  - `forge wizard --prompt "..."` — сканирует репо, прогоняет baseline, задаёт уточняющие вопросы при неоднозначности запроса (протокол QUESTIONS) и собирает полный `tasks.wizard.yaml`: задачи, scope, acceptance, бюджеты, гейты — плюс прогноз стоимости. Acceptance, который ещё не может пройти (тестовая команда раньше задачи с тестами в репо без тестов), убирается с явным предупреждением. Черновик подтверждает человек (гейт №1), затем запускает.
  - `forge wizard --recipe feature` — готовые рецепты из `config/recipes/` (`feature`, `test-coverage`, `docs-sync`) вообще без вызова LLM ($0).
  - `forge import --spec SPEC.md` — черновик очереди задач из существующей спецификации через роль planner.
- **Очередь задач `tasks.yaml`**: DAG с `depends_on`, scope записи на задачу (`scope_paths`), acceptance-команды, бюджеты на задачу, milestone-гейты.
- **Агентный цикл**: coder пишет код инструментами `read_file` / `write_file` / `list_dir` / `run_command` — контроль scope, allowlist команд, установка зависимостей заблокирована на уровне инструмента.
- **Пайплайн на задачу**: coder → acceptance-команды → reviewer (вторая модель) → repair-цикл → `done` / `failed` / `blocked`.
- **Человеческий гейт**: задачи с меткой `gate` приостанавливают прогон до `forge accept <task-id>` (фиксация приёмки, merge локальной ветки). Задачу в `blocked`/`failed` владелец может принять вручную — явный override.
- **Предполётные проверки**: `forge run --dry-run` (прогноз стоимости без запуска) и `forge lint <tasks.yaml>` (валидация контракта + советы по acceptance: тесты заморожены вне scope coder'а, а каждая тестовая команда проходима на позиции задачи в DAG — до того, как потрачен первый цент).
- **Git-интеграция**: ветка `forge/<task-id>` на задачу, локальный коммит после одобрения reviewer; **push никогда не выполняется**. Работает и на не-git проектах (ветвление пропускается с записью в журнале).
- **Пресеты провайдеров** (`config/providers/*.yaml`): любой OpenAI-совместимый endpoint — DeepSeek, бесплатные модели OpenRouter, локальный Ollama и т.п. Модели и цены живут в `config/models.yaml`, а не в коде.
- **Mock-режим** `FORGE_MOCK=1`: весь цикл без API-ключа — для CI и разработки.
- **Веб-UI только на чтение** (`forge ui`): канбан состояний задач, просмотр журнала событий по задаче, отчёт по стоимости прогона и браузерная форма (`/wizard?file=<черновик>`) для правки wizard-черновика карточками задач.
- **Возобновляемые прогоны**: история диалога агента снапшотится после каждого шага; `forge resume <run_id>` подхватывает убитый прогон с места остановки.
- **Отчёт простым языком**: `forge report --plain` — что сделано, что не получилось, что делать дальше. Без археологии по YAML.

## Установка

Требуется Python ≥ 3.12 (эталонная платформа — Windows + Git Bash; Linux/macOS работают идентично).

```bash
git clone https://github.com/Xarawg/agent-forge.git
cd agent-forge
python -m venv .venv
source .venv/Scripts/activate     # Git Bash на Windows; .venv/bin/activate на Linux/macOS
pip install -e .
```

Для реального (не mock) прогона — скопируйте `.env.example` в `.env` и добавьте ключ провайдера:

```bash
cp .env.example .env
# отредактируйте .env: DEEPSEEK_API_KEY=sk-...   (или OPENROUTER_API_KEY, или без ключа для Ollama)
```

Проверка установки без API-ключа:

```bash
FORGE_MOCK=1 pytest -q
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /tmp/demo
forge status && forge report --plain
```

## Сценарии использования — от нуля до рабочего прогона

Все команды ниже запускаются из каталога agent-forge; `--target` указывает на *ваш* проект.

### A. Новый проект (пустая папка, ни кода, ни спецификаций)

```bash
forge init --target /path/to/new-project
forge wizard --target /path/to/new-project --prompt "CLI-калькулятор: пакет calc с add(a,b), python -m calc 2 3, pytest-тесты"
# → /path/to/new-project/tasks.wizard.yaml — проверьте черновик (гейт №1), затем:
forge run --tasks /path/to/new-project/tasks.wizard.yaml --target /path/to/new-project
forge report --plain
```

Wizard печатает прогноз стоимости до любого запуска. С профилем `careful` (по умолчанию) каждая задача ждёт `forge accept <task-id>` — вы смотрите результат, принимаете, затем `forge resume <run_id>`.

### B. Легаси-проект (много кода, ни спеки, ни AGENTS.md)

Wizard сканирует дерево, определяет стек и существующие команды тестов, прогоняет их как baseline и чертит задачи под реальные соглашения проекта. Для самого безопасного первого прогона начните с рецепта покрытия тестами:

```bash
forge wizard --target /path/to/legacy --recipe test-coverage      # без вызова LLM, $0
forge run --tasks /path/to/legacy/tasks.wizard.yaml --target /path/to/legacy
```

Если baseline уже красный, `forge init`/wizard честно скажут об этом и остановятся — сначала чините проект, потом запускайте агентов.

### C. Проект с AGENTS.md / SPEC.md и другой документацией

agent-forge читает то, что уже есть: `AGENTS.md` в корне целевого проекта попадает в контекст coder'а (стек, соглашения, команды тестов — образец в `prompts/60_target_AGENTS.md`), а спецификация может вести всю очередь:

```bash
forge import --spec /path/to/project/SPEC.md --out tasks.draft.yaml   # черновик planner'а (гейт №1)
forge lint tasks.draft.yaml                                           # контракт + советы по acceptance
forge run --tasks tasks.draft.yaml --target /path/to/project --spec /path/to/project/SPEC.md
```

`--spec` прикладывает выдержку из спеки к промпту каждой задачи; `canon_snapshot` в `tasks.yaml` так же закрепляет канонический файл (например, `canon/decisions.json`). Каталог `canon/` для агентов всегда read-only.

### D. Ручной режим: свой tasks.yaml

Напишите или отредактируйте очередь вручную (схема: [docs/CONFIGURATION.ru.md](docs/CONFIGURATION.ru.md) §4), затем:

```bash
forge lint tasks.yaml                    # проверка до траты денег
forge run --tasks tasks.yaml --dry-run   # прогноз стоимости, ничего не выполняется
forge run --tasks tasks.yaml --target /path/to/repo
forge status                             # таблица задач
forge log <task-id>                      # полный журнал событий задачи
forge accept <task-id>                   # человеческий гейт №3 (и ручной override для blocked/failed)
forge resume <run_id>                    # продолжить после остановки или гейта
forge report --plain                     # итог простым языком
forge ui                                 # канбан-дашборд на http://127.0.0.1:8765
```

Десять реальных полевых сценариев с полными цепочками команд — greenfield от спецификаций, contract-first API, внедрение в легаси, спасение чужого vibe-code, дрейф документации и другое: [docs/USECASES.ru.md](docs/USECASES.ru.md). Те же десять в виде иллюстрированного двуязычного гида: [docs/cases.html](docs/cases.html) (открыть raw или через GitHub Pages).

## Справочник команд

| Команда | Назначение |
|---|---|
| `forge init [--target DIR] [--profile careful\|normal\|fast] [--force] [--no-check]` | Подготовить проект: определение стека, git init, skeleton `tasks.yaml`, baseline-проверки |
| `forge wizard --prompt "..." [--recipe NAME] [--profile ...] [--yes] [--out FILE] [--no-check]` | Черновик полной настройки (задачи/acceptance/бюджеты/гейты) из промпта своими словами, файла с промптом или рецепта |
| `forge import --spec SPEC.md [--out FILE]` | Черновик `tasks.yaml` из существующей спецификации через planner |
| `forge lint <tasks.yaml>` | Предполётная проверка: ошибки контракта + советы по acceptance (заморозка scope, проходимость на позиции в DAG) |
| `forge run --tasks F [--target DIR] [--spec SPEC.md] [--dry-run] [--provider PRESET]` | Запуск очереди; `--dry-run` печатает прогноз стоимости и ничего не выполняет |
| `forge resume <run_id> [--target DIR]` | Продолжить остановленный/приостановленный прогон со снапшотов на диске |
| `forge status [run_id]` | Таблица задач: состояние, токены, стоимость, починки, заметки |
| `forge log <task-id> [--run ID]` | Полный журнал событий одной задачи |
| `forge report [run_id] [--plain]` | Сводка по стоимости/токенам; `--plain` — итог простым языком и следующие шаги |
| `forge accept <task-id> [--run ID] [--target DIR]` | Человеческий гейт №3: принять done-задачу (merge ветки); также ручной override для `blocked`/`failed` |
| `forge ui [--port 8765]` | Веб-дашборд только на чтение: канбан, просмотр логов, отчёт по стоимости, редактор wizard-черновика (`/wizard?file=...`) |

Профили капов для `init`/`wizard`: `careful` (задача ≤ $0.30, гейт после каждой задачи — первые прогоны и free-модели), `normal` (дефолты models.yaml), `fast` (крупные задачи, редкие гейты).

## Конфигурация

Провайдеры — YAML-пресеты (`config/providers/*.yaml`), модели/цены/бюджеты — в `config/models.yaml`, и всё переопределяется переменными окружения (`FORGE_BASE_URL`, `FORGE_API_KEY`, `FORGE_<ROLE>_MODEL`, `FORGE_MOCK`, ...). Полный справочник: [docs/CONFIGURATION.ru.md](docs/CONFIGURATION.ru.md) ([English version](docs/CONFIGURATION.md)). Спецификация инструмента (FR/NFR): [docs/SPEC.ru.md](docs/SPEC.ru.md) ([English version](docs/SPEC.md)).

## Веб-UI

```bash
forge ui            # http://127.0.0.1:8765
forge ui --port 9000
```

Открывает локальный офлайн-дашборд (без CDN, только stdlib), который читает `runs/`: селектор прогонов с общей стоимостью в шапке, канбан-доска с колонками `queued → running → validating → review → blocked → failed → done` и кликабельные карточки задач, открывающие боковую панель с последними событиями журнала. Переключатель превращает доску в таблицу отчёта по задачам (состояние, токены, стоимость, починки) с итогами. `/wizard?file=<черновик>` рендерит wizard-черновик как редактируемые карточки задач (подтверждённый YAML записывается обратно в тот же файл). Страница автообновляется каждые 3 секунды и никогда не меняет состояние прогона.

## Docker

```bash
docker build -t agent-forge .
docker run --rm --env-file .env \
  -v ${PWD}/runs:/app/runs -v /path/to/target-repo:/target \
  agent-forge run --tasks config/tasks.example.yaml --target /target
```

или через compose (`export FORGE_TARGET_REPO=/path/to/target-repo`, затем `docker compose run --rm forge run ...`; `docker compose run --rm test` запускает pytest внутри образа).

## Разработка

```bash
pip install -e ".[dev]"
pytest -q            # все тесты работают в mock-режиме, API-ключ не нужен
ruff check .
mypy --strict forge/
```

CI: GitHub Actions (`.github/workflows/ci.yml`, ubuntu × windows, Python 3.12/3.13) и GitLab CI (`.gitlab-ci.yml`).

## Безопасность

Scope-контроль и allowlist команд — ограничения против ошибок модели, **а не песочница**: разрешённые команды (`python`, `npm`, …) могут исполнить произвольный код, а `acceptance`-команды — доверенный shell владельца. Точные границы и рекомендации: [SECURITY.md](SECURITY.md).

## Лицензия

[MIT](LICENSE) © 2026 agent-forge contributors.
