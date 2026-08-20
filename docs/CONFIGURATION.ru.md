# CONFIGURATION — полный справочник по конфигурации agent-forge

Как переиспользовать agent-forge в любом другом проекте: переменные окружения,
`config/models.yaml`, пресеты провайдеров, `tasks.yaml`, библиотека промптов,
требования к целевому репозиторию, заметки по платформам.

Источники истины в коде: `forge/config.py` (env + models.yaml + пресет),
`forge/models.py` (схема tasks.yaml), `forge/prompts.py` (промпты).

## 1. Переменные окружения

Все переменные читаются дважды за запуск: из `os.environ` (приоритет) и из
файла `.env` в корне agent-forge (простой парсер `KEY=VALUE`, без внешних
зависимостей; `forge/config.py:load_env_file`). `.env` — в `.gitignore`,
в журнал прогонов секреты не пишутся (NFR-3).

| Переменная | Формат | Дефолт | Где читается |
|---|---|---|---|
| `FORGE_HOME` | путь | родитель пакета `forge/` (исходный checkout) | `forge/config.py:forge_root` — корень, откуда берутся `config/`, `prompts/`, `runs/`, `.env` |
| `FORGE_PROVIDER` | путь к пресету (относительный — от корня) | `config/providers/deepseek.yaml` | `load_config` |
| `FORGE_MOCK` | `1` / `true` / `yes` (без учёта регистра) | выкл. | `load_config` → `make_client` (MockClient вместо OpenAI API) |
| `FORGE_MOCK_SCENARIO` | `default` / `rogue` | `default` | `MockClient.scenario` (`forge/llm.py`); `rogue` — coder сначала пытается писать вне scope (проверка scope-контроля) |
| `FORGE_BASE_URL` | URL OpenAI-совместимого endpoint | `provider.base_url` из пресета | `load_config`, общий fallback для всех ролей |
| `FORGE_API_KEY` | строка ключа | ключ из `api_key_env` пресета | `load_config`, общий fallback для всех ролей |
| `FORGE_<ROLE>_BASE_URL` | URL | `FORGE_BASE_URL` → пресет | `load_config`; ROLE ∈ PLANNER, CODER, REVIEWER, REPAIR |
| `FORGE_<ROLE>_API_KEY` | строка ключа | `FORGE_API_KEY` → `api_key_env` пресета | `load_config` |
| `FORGE_<ROLE>_MODEL` | имя модели | пресет `roles.<role>.model` → `models.yaml` | `load_config` |
| `<API_KEY_ENV>` из пресета | напр. `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `PROVOD_API_KEY` | — | `load_config`, если нет `FORGE_*_API_KEY` |

Порядок разрешения для роли (на примере coder):
`base_url`: `FORGE_CODER_BASE_URL` → `FORGE_BASE_URL` → `provider.base_url` из пресета.
`api_key`: `FORGE_CODER_API_KEY` → `FORGE_API_KEY` → значение переменной, названной в `api_key_env` пресета.
`model`: `FORGE_CODER_MODEL` → `roles.coder.model` пресета → `roles.coder.model` из `models.yaml`.

Если не mock-режим, ключа нет и пресет требует `api_key_env` — `load_config`
падает с понятной ошибкой (предлагает задать ключ, `FORGE_MOCK=1` или пресет ollama).

## 2. config/models.yaml

Модельная карта ролей и бюджеты. Смена модели/прайса = правка этого файла, не кода.

```yaml
roles:
  planner:                    # planner / coder / reviewer / repair — все четыре обязательны
    model: deepseek-v4-pro    # дефолт, если пресет провайдера не переопределяет роль
    max_tokens: 16000         # лимит completion-токенов на ОДИН вызов (обрывает write_file больших файлов — не занижать)
    temperature: 0.2
    price_per_m_in: 0.435     # USD за 1M входных токенов — из прайса провайдера
    price_per_m_out: 0.87     # USD за 1M выходных токенов
  coder:    { ... }
  reviewer: { ... }
  repair:   { ... }

budgets:                      # дефолты; задача может переопределить свои (см. tasks.yaml)
  per_task_max_tokens: 2000000    # кап токенов (in+out) на задачу; от зацикливания, не от честной работы
  per_run_max_cost_usd: 2.00      # кап стоимости прогона; достигнут — прогон останавливается
  per_day_max_cost_usd: 5.00      # кап стоимости за сутки UTC по всем runs/*/events.jsonl
  repair_max_iterations: 3        # глубина repair-цикла (FR-3)

retry:                        # отказы провайдера: 429/5xx и сетевые ошибки
  max_attempts: 5
  backoff_seconds: [5, 15, 45, 120, 300]   # пауза после i-й попытки; free-лимиты RPM сюда же
```

Цены — декларативные: `forge report` и бюджетные капы считают стоимость отсюда
(`RoleConfig.cost_usd`). Перед прогоном сверять с актуальным прайсом провайдера.

## 3. config/providers/*.yaml — пресет провайдера

Формат (разбор — `forge/config.py:load_config`):

```yaml
provider:
  name: provod                       # человекочитаемое имя (в run.json)
  base_url: https://api.provod.ai/v1 # OpenAI-совместимый endpoint ({base_url}/chat/completions)
  api_key_env: PROVOD_API_KEY        # имя env-переменной с ключом; пусто/отсутствует = ключ не нужен (ollama)
  api_style: openai-compatible       # информационное поле, код не читает
  limits:                            # информационный блок (rpm, дневные лимиты), код не читает
    rpm: null

roles:                               # переопределение моделей ролей под этого провайдера (опционально)
  planner:  { model: deepseek-v4-pro }
  coder:    { model: deepseek-v4-pro }
  reviewer: { model: deepseek-v4-flash }   # reviewer — дешёвая чек-листовая роль
  repair:   { model: deepseek-v4-pro }

fallback_models:                     # перебор при перманентном отказе основной модели роли
  - deepseek-v4-flash
  - glm-5
```

Существующие пресеты: `deepseek.yaml` (дефолт), `openrouter-free.yaml`
(бесплатные модели `:free`), `ollama.yaml` (локально, без ключа), `provod.yaml`.
Свой провайдер = новый файл здесь же + `--provider config/providers/my.yaml`
или `FORGE_PROVIDER=...`.

## 4. tasks.yaml — очередь задач

Схема (парсинг и валидация — `forge/models.py:load_tasks`):

```yaml
package: my-package              # имя пакета (дефолт — имя файла)
canon_snapshot: canon/decisions.json   # опционально: файл из target-репо, прикладывается выдержкой к промпту задачи

tasks:
  - id: my-task-1                # обязательно; kebab-case: ^[a-z0-9][a-z0-9-]*$; уникальный
    title: "Короткое имя"        # дефолт — id; показывается в status/UI
    spec_ref: "SPEC.md §3.1"     # ссылка на источник истины (информативно, идёт в промпт)
    scope_paths:                 # обязательно, непусто: куда coder МОЖЕТ писать
      - "src/feature/**"         # gitignore-подобные маски: ** — через /, * — внутри сегмента
    depends_on: []               # DAG; циклы и висячие ссылки — ошибка загрузки
    acceptance:                  # команды гейта №2; исполняет runner (доверенные), все должны дать exit 0
      - "cd src/feature && npm test"
    budget:                      # опционально: перезадачные капы (иначе дефолты models.yaml)
      max_tokens: 150000
      max_cost_usd: 0.50
    gate: milestone-1            # опционально: метка милстоуна (см. ниже)
```

Семантика:

- **Порядок** — топологический по `depends_on`; при равенстве — порядок в файле.
  Задачи идут последовательно, параллелизма нет (NFR-2, free-лимиты).
- **Состояния**: `queued → running → validating → review → done | failed | blocked`.
  Repair-итерация — повторный `running`; число итераций — в `tasks/<id>.json`.
  `DISPUTE`/`BLOCKED`/`GAP` от агента → `blocked` (решает человек), `STUCK`/
  исчерпание шагов/итераций → `failed`.
- **gate**: после того как задача с меткой `gate` дошла до `done`, прогон встаёт
  на паузу до явного `forge accept <id>` (человеческий гейт №3: accept фиксирует
  приёмку и мержит ветку `forge/<id>` локально). Продолжение — `forge resume <run_id>`.
  Гейт сдерживает только `done`-задачи: `failed` волну не блокирует (by design).
- **resume**: `forge run`/`resume` пропускает задачи в `done`; снапшоты диалога
  `tasks/<id>.<phase>.history.json` позволяют продолжить убитую посреди фазы задачу
  с контекстом и сохранённым счётчиком шагов.
- **acceptance** исполняется runner'ом как есть (shell, cwd = корень target-репо,
  таймаут 300 с на команду) — whitelist инструментов на них НЕ действует.

## 5. prompts/ — библиотека промптов

Вся текстовка промптов — файлы в `prompts/`, не в коде (SPEC §7):

| Файл | Назначение |
|---|---|
| `00_system.md` | системный промпт, общий для всех ролей |
| `10_planner.md` | planner: SPEC → черновик tasks.yaml (`forge import`) |
| `20_codegen.md` | coder: правила цикла, маркеры DONE/BLOCKED/GAP, запрет коммита |
| `30_reviewer.md` | reviewer: чек-лист ревью, вердикты APPROVE/REWORK/REJECT |
| `40_repair.md` | repair: починка по вердикту, маркеры STUCK/DISPUTE |
| `50_task_template.md` | шаблон промпта задачи (плейсхолдеры `{{task.id}}` и т.п.) |
| `60_target_AGENTS.md` | образец AGENTS.md для целевого репозитория |

Версионирование: каталог под git; версия библиотеки фиксируется в `run.json`
(`prompts_version`) как git-хеш последнего коммита, трогавшего `prompts/`
(вне git — sha256 содержимого; `forge/prompts.py:prompts_version`).

## 6. Как натравить forge на другой проект

```bash
pip install -e .            # в репозитории agent-forge
forge run --tasks path/to/tasks.yaml --target /path/to/target-repo --spec path/to/SPEC.md
```

- `--tasks` — очередь задач (см. §4). Черновик из спеки: `forge import --spec SPEC.md --out tasks.draft.yaml`, затем вычитать и поправить руками (гейт №1).
- `--target` — корень целевого репозитория (дефолт — текущий каталог). Все пути
  инструментов и acceptance-команды относительны ему.
- Требования к целевому репо:
  - Желателен `AGENTS.md` в корне (образец — `prompts/60_target_AGENTS.md`):
    стек, команды тестов, соглашения — coder читает его как часть контекста.
  - Acceptance-команды должны работать из корня target-репо (тесты, линтеры).
  - git необязателен: без репозитория ветвление/коммит пропускаются с записью
    в журнал. С git — ветка `forge/<task-id>` на задачу, локальный коммит после
    APPROVE; push никогда не делается (NFR-5).
  - Зависимости ставит владелец заранее: агенту `npm install`/`pip install` и т.п.
    заблокированы на уровне инструмента (AF-10).
- Прогон и UI независимы: `forge ui` читает `runs/` и работает параллельно.

## 7. Замечания по платформам

- **Windows (референс, NFR-1)**: Git Bash; пути с пробелами допустимы. Дочерним
  процессам прокидываются дефолты `ProgramFiles` / `ProgramFiles(x86)` /
  `ProgramW6432` — без них NuGet/`dotnet` падают в урезанных окружениях
  (`forge/tools.py:_WINDOWS_ENV_DEFAULTS`). Команды исполняются через `shell=True`
  (cmd-семантика для runner и инструментов).
- **Linux/macOS**: особенностей нет — чистый Python, состояние на диске, демонов
  нет. CI матрица (GitHub Actions) гоняет ubuntu + windows на Python 3.12/3.13.
- **Docker**: образ на `python:3.12-slim`; `runs/` и target-репо — volume'ами
  (см. README). В контейнере `FORGE_HOME` не нужен — корень определяется по пакету.
