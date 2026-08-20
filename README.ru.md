# agent-forge

Инфраструктура агентной кодогенерации: владелец запускает локально, инструмент
разбивает пакет спецификации на задачи и гоняет их через LLM-агентов на
OpenAI-совместимом API (DeepSeek, бесплатные модели OpenRouter `:free`,
локальные через Ollama и т.п.). Спецификация инструмента: [docs/SPEC.md](docs/SPEC.md).

> Каноническое описание — английское [README.md](README.md); этот файл может
> отставать. Полный справочник по конфигурации: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Возможности

- Агентный цикл coder → автоматическая валидация (acceptance-команды) → reviewer →
  repair (до 3 итераций) → done/failed (SPEC §FR-2, §FR-3).
- Scope-контроль: `write_file` только в `scope_paths` задачи; `canon/` — всегда
  read-only; нарушения блокируются и логируются (§6.5, §7).
- Журнал прогонов `runs/<run_id>/events.jsonl` (токены, стоимость, команды),
  состояния задач `runs/<run_id>/tasks/<id>.json` (§FR-4).
- Бюджетные капы per-task / per-run / per-day; превышение → задача в `blocked` (§FR-5).
- Провайдеры — пресетами в `config/providers/`; модели — в `config/models.yaml`,
  не в коде (§FR-6).
- Mock-режим `FORGE_MOCK=1` — весь цикл без API-ключа, для CI и разработки (§6.3).
- Воспроизводимость: run.json фиксирует модели и версию промптов (§FR-7).
- Git: ветка `forge/<task-id>` и локальный коммит после гейта reviewer; push —
  только владельцем вручную (NFR-5). Merge ветки — по явному `forge accept`.
- Веб-UI `forge ui` — канбан состояний задач, лог-вьюер событий, отчёт по прогону
  (только чтение `runs/`).

## Установка и запуск локально (Windows 10/11 + Git Bash)

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e ".[dev]"

cp .env.example .env   # вписать DEEPSEEK_API_KEY или OPENROUTER_API_KEY
```

Проверка без API-ключа (mock-режим):

```bash
FORGE_MOCK=1 pytest -q
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /path/to/repo
forge status
forge report
forge log <task_id>
forge ui          # канбан прогонов на http://127.0.0.1:8765
```

Реальный прогон поверх целевого репозитория (из корня agent-forge):

```bash
forge run --tasks config/tasks.example.yaml --target /path/to/repo --spec SPEC.md
forge status                 # таблица задач прогона
forge report                 # токены, стоимость, модели, версия промптов
forge accept <task_id>       # человеческий гейт №3: merge ветки, продолжение
forge resume <run_id>        # продолжить после остановки/гейта
forge import --spec <SPEC.md пакета> --out tasks.draft.yaml   # черновик задач (гейт №1)
```

`--target` по умолчанию — текущий каталог. Без git-репозитория в target
ветвление/коммит пропускаются (запись в журнале).

## Запуск в Docker

```bash
docker build -t agent-forge .
docker run --rm --env-file .env \
  -v ${PWD}/runs:/app/runs -v /path/to/target-repo:/target \
  agent-forge run --tasks config/tasks.example.yaml --target /target
```

или через compose:

```bash
export FORGE_TARGET_REPO=/path/to/target-repo
docker compose run --rm forge run --tasks config/tasks.example.yaml --target /target
docker compose run --rm forge report
docker compose run --rm test     # pytest внутри образа
```

## Запуск на Linux-стенде

Тот же путь, что локально: Python 3.12+, `pip install -e ".[dev]"`, `.env`,
`forge run ...`. Особенностей нет: инструмент — чистый Python, состояние на
диске, фоновых демонов нет (NFR-2). Под systemd/cron запускать не нужно —
одна команда = один прогон.

## Тесты и качество

```bash
pytest -q            # все тесты одной командой (mock-режим, ключ не нужен)
ruff check .
mypy --strict forge/
```

CI: GitHub Actions (`.github/workflows/ci.yml`: ubuntu + windows, Python
3.12/3.13) и GitLab CI (`.gitlab-ci.yml`): install → lint (ruff) → typecheck
(mypy) → test → build (docker).

## Конфигурация провайдеров (§FR-6)

- Дефолт: DeepSeek direct (`config/providers/deepseek.yaml`), ключ `DEEPSEEK_API_KEY`.
- Бесплатно: OpenRouter `:free` (`config/providers/openrouter-free.yaml`), ключ
  `OPENROUTER_API_KEY`; лимиты ~20 RPM / ~50 запросов в день отрабатываются
  backoff'ом из `models.yaml`, fallback-модели перебираются по порядку.
- Локально: Ollama (`config/providers/ollama.yaml`), ключ не нужен.

Выбор пресета: `--provider config/providers/openrouter-free.yaml` или
`FORGE_PROVIDER=...` в `.env`. Переопределения по ролям:
`FORGE_<ROLE>_BASE_URL / _API_KEY / _MODEL`, общий fallback `FORGE_BASE_URL`.
Полный справочник — [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Структура

```
forge/      — пакет (cli, runner, agents, llm, tools, journal, ui, report)
prompts/    — библиотека промптов ролей (версионируется git; текстовка не в коде)
config/     — models.yaml, providers/*.yaml, tasks.example.yaml
runs/       — журналы прогонов (в .gitignore)
tests/      — pytest, одна команда
docs/       — SPEC.md, ARCHITECTURE.md, DECISIONS.md, ANALYTICS.md, CONFIGURATION.md
```

Документация — русская; код и идентификаторы — английские.

## Лицензия

[MIT](LICENSE) © 2026 Atlas project contributors.
