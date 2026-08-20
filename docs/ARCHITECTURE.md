# ARCHITECTURE — agent-forge

Версия 0.1 · 19.08.2026 · По спецификации `docs/design/specs/agent-forge/SPEC.md` v1.0.

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
| `cli.py` | argparse: run / resume / status / log / report / accept / import |
| `config.py` | models.yaml + пресет провайдера + .env; сборка RoleConfig по ролям |
| `models.py` | tasks.yaml: парсинг, валидация, DAG, состояния задач |
| `llm.py` | `LLMClient`-протокол; `OpenAIClient` (retry/backoff, fallback-модели); `MockClient` |
| `tools.py` | Инструменты агента; scope-контроль; whitelist команд |
| `agents.py` | Цикл «модель ↔ инструменты»; одношаговый reviewer; маркеры |
| `runner.py` | Оркестрация фаз, бюджеты, гейты, git |
| `journal.py` | run.json, events.jsonl, tasks/<id>.json |
| `report.py` | Сводки status/report из журнала |
| `prompts.py` | Загрузка/рендер промптов; версия библиотеки (git hash / sha256) |

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

## Журнал (§5)

Событие: `{ts, run_id, task_id, phase, role, model, tokens_in, tokens_out,
cost_usd, command?, exit_code?, note}`. Фазы: `run`, `gate`, `state`, `git`,
`coder`, `repair`, `validate`, `review`, `plan`, `budget`. Сырые ответы моделей
(до 2000 символов) — в `note` событий вызова; секреты в журнал не пишутся
(ключи живут только в `.env` и переменных окружения, NFR-3).
