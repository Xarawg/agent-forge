# ARCHITECTURE — agent-forge

Версия 0.2 · 21.08.2026 · По спецификации `docs/SPEC.md` v1.3.

## Обзор

Один CLI (`forge`), одна команда = один прогон (NFR-2). Состояние целиком на
диске в `runs/<run_id>/` — процесс можно убить и продолжить `forge resume`.
Параллелизма нет: задачи идут последовательно в топологическом порядке DAG
(§7 — free-лимиты провайдеров).

## Поток прогона (`forge run`)

```
tasks.yaml ──load_tasks──► DAG (topo_order)
        │
        ▼  для каждой задачи
   ┌─────────────┐   blocked  ◄── бюджетные капы (per-task/run/day)
   │ gate check  │── пауза ◄── предыдущая gated-задача done и не accepted
   └─────────────┘
        ▼ running
   coder-цикл (run_tool_agent): модель ↔ tools(read/write/list/run_command)
        ▼ маркер DONE / BLOCKED / GAP / STEPS_EXHAUSTED
   validating: acceptance-команды (доверенные, из tasks.yaml)
        ▼
   review: reviewer-роль по чек-листу prompts/30 (без инструментов)
        ▼ APPROVE+зелёное ──► git commit ──► done
        ▼ REWORK/красное ──► repair-цикл (≤3 итераций) ──► failed
        ▼ REJECT ──► failed
```

## Модули `forge/`

| Модуль | Ответственность |
|---|---|
| `cli.py` | argparse: run / resume / status / log / report / init / wizard / lint / accept / ui / import |
| `config.py` | models.yaml + пресет провайдера + .env; сборка RoleConfig по ролям |
| `models.py` | tasks.yaml: парсинг, валидация, DAG, состояния задач |
| `llm.py` | `LLMClient`-протокол; `OpenAIClient` (retry/backoff, fallback-модели); `MockClient` |
| `tools.py` | Инструменты агента; scope-контроль; whitelist команд |
| `agents.py` | Цикл «модель ↔ инструменты»; одношаговый reviewer; маркеры |
| `runner.py` | Оркестрация фаз, бюджеты, гейты, git |
| `journal.py` | run.json, events.jsonl, tasks/<id>.json |
| `report.py` | Сводки status/report из журнала (вкл. `--plain`); игнорирует снапшоты `*.history.json` |
| `prompts.py` | Загрузка/рендер промптов; версия библиотеки (git hash / sha256) |
| `detect.py` | Определение стека целевого проекта: тестовые команды, файлы пакетов (Python/Node/.NET) |
| `init.py` | `forge init`: git init, skeleton tasks.yaml из найденных проверок, baseline-прогон |
| `wizard.py` | `forge wizard`: скан репо + baseline + черновик planner'а / рендер рецепта; интервью QUESTIONS; нормализация scope (`dir/` → `dir/**`) |
| `profiles.py` | Профили капов `careful` / `normal` / `fast` (бюджеты + плотность гейтов) |
| `lint.py` | `forge lint`: валидация контракта tasks.yaml + советчик по заморозке acceptance |
| `dryrun.py` | `forge run --dry-run`: прогноз стоимости очереди без выполнения |
| `ui.py` + `ui_static/` | Веб-UI только на чтение (stdlib http.server, без CDN): канбан, лог-вьюер, отчёт, редактор wizard-черновика |

## Ключевые механизмы

### Scope-контроль (§FR-2, §6.5, §7)
`ToolBox.write_file` нормализует путь, запрещает выход за корень target-репо
(`..`), всегда запрещает `canon/`, затем матчит на gitignore-подобные маски
`scope_paths` (`**` — через разделители, `*` — внутри сегмента). Нарушение
возвращается модели как `ERROR:` и пишется в журнал с пометкой `SCOPE_VIOLATION`.

### Бюджеты (§FR-5)
Проверяются перед стартом задачи и перед каждой repair-итерацией. per-day кап
считается суммой `cost_usd` по всем `runs/*/events.jsonl` за текущие сутки UTC.
Превышение → задача в `blocked`, причина в журнале и в `forge status`.

### Воспроизводимость (§FR-7)
`run.json` фиксирует: провайдер, mock-флаг, модели ролей, версию промптов
(git-хеш последнего коммита `prompts/`; вне git — sha256 содержимого).
`forge report` считает цену по прайсу из `config/models.yaml`.

### Mock-режим (§6.3)
`MockClient` — детерминированный стенд по ролям: coder пишет
`<scope>/mock_output.md` и завершает DONE; repair пишет `mock_state.txt` с
`iteration-N`; reviewer — APPROVE при зелёном acceptance, иначе REWORK;
planner — валидный YAML-черновик. Сценарий `FORGE_MOCK_SCENARIO=rogue`
проверяет scope-контроль. Токены считаются от длины сообщений, стоимость —
по прайсу конфига, так что отчёты и капы прогоняются по-настоящему.

### Git (§1.4, NFR-5)
Если target — git-репозиторий: на задачу создаётся ветка `forge/<task-id>`,
после APPROVE — локальный коммит записанных файлов. `forge accept` мержит ветку
локально (`--no-ff`). Push отсутствует как класс. Если target не git-репозиторий —
фаза пропускается с записью в журнал.

### Accept override (§FR-4)
`forge accept` на задаче в `blocked`/`failed` переводит её в `done` с пометкой
`override`. Без этого задача, упершаяся в кумулятивный per-task кап токенов, была
вечным тупиком: токены копятся между resume, и предстартовая проверка бюджета
блокировала бы каждый повтор до вызова модели.

### Снапшоты истории (NFR-2)
После каждого шага агента диалог снапшотится в `tasks/<id>.<phase>.history.json`;
resume продолжает убитую посреди фазы задачу с контекстом и сохранённым счётчиком
шагов. Эти файлы — не состояния задач: report/UI/status пропускают их по имени.

## Журнал (§5)

Событие: `{ts, run_id, task_id, phase, role, model, tokens_in, tokens_out,
cost_usd, command?, exit_code?, note}`. Фазы: `run`, `gate`, `state`, `git`,
`coder`, `repair`, `validate`, `review`, `plan`, `budget`. Сырые ответы моделей
(до 2000 символов) — в `note` событий вызова; секреты в журнал не пишутся
(ключи живут только в `.env` и переменных окружения, NFR-3).
