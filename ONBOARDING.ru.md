# Onboarding: вход в проект agent-forge за 30 минут

> English version: [ONBOARDING.md](ONBOARDING.md).
> Этот файл — единственный, который нужно прочитать новичку целиком.
> Остальное — по ссылкам из него.

## Что это за проект

agent-forge — локальный оркестратор LLM-кодогенерации: вы описываете работу
очередью задач (вручную, из спеки или словами через wizard), агенты пишут код
по задачам, каждая задача проверяется **вашими** командами (тесты, линтеры),
а между этапами стоят человеческие гейты. Модель — любая OpenAI-совместимая;
деньги ограничены капами; всё журналируется. Полная теория и сравнение с
альтернативами — [docs/GUIDE_LLM.ru.md](docs/GUIDE_LLM.ru.md).

## Установка (5 минут)

Требования: Windows 10/11 + Git Bash (или Linux/macOS), Python 3.12+, git.

```bash
git clone https://github.com/Xarawg/agent-forge.git
cd agent-forge
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[dev]"
```

Проверка без API-ключа и без денег (mock-режим):

```bash
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /tmp/any-folder --dry-run
pytest -q    # 105+ тестов, должны быть зелёные
```

## Первый прогон на своём проекте (15 минут)

```bash
# 1. Ключ провайдера (любой OpenAI-совместимый; пресеты — config/providers/)
cp .env.example .env   # впишите FORGE_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY

# 2. Подготовка вашего проекта (git, baseline-проверки, профиль капов)
forge init --target /path/to/project --profile careful

# 3. Большой проект? Сначала карта сущностей — детерминированно, $0:
forge map --target /path/to/project
# → docs/ENTITIES.md (вам) + canon/entities.json (агентам: анти-дубли, соседи по импортам)

# 4. Черновик задач словами (один LLM-вызов) или детерминированный рецепт:
forge wizard --target /path/to/project --prompt "что нужно сделать"
forge wizard --target /path/to/project --recipe test-coverage   # без LLM, $0

# 5. Гейт №1: откройте tasks.wizard.yaml, проверьте/поправьте задачи
forge lint /path/to/project/tasks.wizard.yaml

# 6. Прогон
forge run --tasks /path/to/project/tasks.wizard.yaml --target /path/to/project
```

## Как следить за прогоном

```bash
forge status                 # таблица задач; если прогон ждёт вас — строка ⏸ с командой
forge log <task-id>          # полный журнал событий задачи (вызовы модели, команды)
forge report --plain         # итог простым языком: сделано N из M, потрачено $X
forge ui                     # канбан на http://127.0.0.1:8765 (только чтение)
```

Профиль `careful` останавливается после каждой задачи: смотрите diff,
затем `forge accept <task-id>` и `forge resume <run_id>`. DISPUTE/failed —
не катастрофа, а точка вашего решения: разберитесь через `forge log`,
при необходимости примите вручную тем же `forge accept`.

## Куда что ложится (карта репозитория)

| Путь | Что там |
|---|---|
| `forge/` | код инструмента (runner, agents, wizard, map, report…) |
| `prompts/` | библиотека промптов ролей (00 system … 60 AGENTS) |
| `config/` | models.yaml (роли/цены/капы), providers/*.yaml, recipes/*.yaml |
| `docs/` | SPEC (нормативная), GUIDE_LLM (теория), USECASES (кейсы), DECISIONS (журнал решений AF-*) |
| `canon/entities.json` | карта сущностей этого репо (результат `forge map`) |
| `tests/` | pytest; mock-режим, API-ключ не нужен |
| `runs/` | журналы прогонов (локально, в git не идут) |

## Как вносить изменения (процесс)

1. Спорные решения — сначала записью в `docs/DECISIONS.md` (формат AF-N).
2. Код — с тестами; перед коммитом: `pytest -q`, `ruff check forge tests`,
   `mypy forge`. Всё это же гоняет CI.
3. Правили поведение агентов — обновите и промпт-библиотеку, и SPEC, и
   USECASES (они описывают наблюдаемое поведение, не желаемое).
4. Поменяли публичную поверхность `forge/` — перегенерируйте карту:
   `forge map --target .` (артефакты коммитятся: `canon/entities.json`,
   `docs/ENTITIES.md`).

## Что читать дальше

- Новичку в LLM-разработке: [docs/GUIDE_LLM.ru.md](docs/GUIDE_LLM.ru.md)
- Реальные сценарии с разбором «под капотом»: [docs/USECASES.ru.md](docs/USECASES.ru.md)
- Конфигурация и контракт tasks.yaml: [docs/CONFIGURATION.ru.md](docs/CONFIGURATION.ru.md)
- Архитектура: [docs/ARCHITECTURE.ru.md](docs/ARCHITECTURE.ru.md)
