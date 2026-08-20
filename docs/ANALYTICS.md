# ANALYTICS — agent-forge: факт по критериям приёмки (SPEC.md §6)

Статус: собрано в сессии 1 (19.08.2026). Прогоны на реальной модели DeepSeek —
за владельцем (SESSIONS.md «После сессии», п.2–4); здесь — факт по mock-режиму
и тестам, шаблон для заполнения реальными прогонами.

## Критерии приёмки — статус

| # | Критерий (SPEC §6) | Статус | Чем подтверждено |
|---|---|---|---|
| 1 | Пилотная задача задана в tasks.example.yaml | ✅ | `config/tasks.example.yaml` → `pilot-1-port-validate-canon` (порт validate_canon.py на TS) |
| 2 | End-to-end прогон на DeepSeek, стоимость ≤ $0.50 | ⏳ ждёт API-ключ владельца | Цепочка проверена в mock: `run → status → report`, см. ниже |
| 3 | Mock-режим FORGE_MOCK=1 без ключа | ✅ | 22 теста зелёные без ключа; CI гоняет pytest с FORGE_MOCK=1 |
| 4 | Repair-цикл: ≤3 итераций или failed с журналом | ✅ | `tests/test_repair.py`: починка на итерации 1 → done; непочиняемое → failed после 3, note в журнале |
| 5 | Scope-контроль блокируется и логируется | ✅ | `tests/test_scope.py` (юнит) + `test_mock_run.py::test_scope_violation_logged` (событие SCOPE_VIOLATION в events.jsonl) |
| 6 | Тесты одной командой; Docker-образ; README local/Docker/Linux | ⚠️ частично | `pytest` — ✅ (22 passed); README — ✅; Dockerfile/compose/CI написаны, но **сборка образа локально не проверена**: Docker Desktop был остановлен на машине сессии |

## Факт: mock-прогон (19.08.2026, FORGE_MOCK=1)

Команды: `forge run --tasks <smoke-tasks.yaml> --target /tmp/forge-target` →
`forge report`. Дымовая задача (1 шт., acceptance на запись файла):

- Результат: задача дошла до `done` (coder → validate → reviewer APPROVE).
- Токены: 1508 (719 in + 40 out у coder-вызова + repair/review по мелочи —
  mock считает токены от длины сообщений).
- Стоимость: $0.0005 по прайсу DeepSeek из `config/models.yaml` (mock использует
  реальный прайс, так что арифметика отчёта — настоящая).
- Repair-итераций: 0. Версия промптов: `sha256:1a5d877f90e2` (каталог ещё не
  под git — сработал fallback, см. DECISIONS AF-03).

Gate-прогон (2 задачи, первая с `gate: pilot-1`): после done первой прогон
остановился, вторая осталась `queued`; после `forge accept` + `resume` —
дошла до `done`. Покрыто `test_gate_blocks_until_accept`.

## Шаблон для реальных прогонов (заполняет владелец, SESSIONS.md п.4)

### Прогон run-20260819-105828 — 19.08.2026 — provod.ai / deepseek-v4-pro

- Задача: pilot-1-port-validate-canon; результат: **failed** (исчерпаны 25 шагов без DONE).
- Токены: 387 200 in + 3 270 out. Стоимость: **$0.1713**.
- Причина: MAX_OUTPUT=4000 резал read_file исходника (10.7K) — агент 25 шагов
  перечитывал файл кусками, не написал ни строки. Калибровка: MAX_OUTPUT→30000,
  EXCERPT_LIMIT→30000, MAX_AGENT_STEPS→40.

### Прогон run-20260819-110410 — 19.08.2026 — provod.ai / deepseek-v4-pro (+ flash reviewer)

- Результат: **blocked** (per-run кап $0.50 → поднят до $2.00; затем per-task кап 400K токенов).
- Токены: 1 739 556 in + 70 103 out. Стоимость: **$0.8166**.
- Артефакт: порт написан (cli.ts 12.5K, schema-check, тесты), CLI запускается.
- Ошибки модели: импорты `./x.js` вместо `./x.ts` (ERR_MODULE_NOT_FOUND при
  type stripping); acceptance `node --test <dir>` падал — на рантайме владельца
  каталог не сканируется, нужен glob (AF-09).
- Виноват и процесс: kill по таймауту 300 c рестартовал фазу с чистым контекстом
  (AF-08) — модель перечитывала и переписывала файлы заново.

### Прогон run-20260819-113603 — 19.08.2026 — provod.ai (финальный)

- Результат: агент снова failed/blocked по шагам и капу; **задача принята
  вручную** (гейт №3, `forge accept`) после ручной проверки acceptance.
- Токены: 2 374 518 in + 95 578 out. Стоимость: **$1.1139**.
- Нарушение промпта: coder поставил node_modules (tsx/esbuild) и сделал
  tsx-мост для тестов, несмотря на запрет в prompts/20 (AF-10). Артефакт
  очищен вручную: node_modules удалён, мост заменён glob-формой, package.json
  без зависимостей.
- Ручная проверка acceptance (владелец-оркестратор):
  `node --test "tools-ts/validate-canon/tests/*.test.ts"` → **47/47 pass**;
  `node tools-ts/validate-canon/src/cli.ts canon/` → 200 решений, 23 модуля,
  143 события, 90 defs, 301 слот, 4 конфига, VALIDATION PASS — идентично
  python-оригиналу.

### Итог пилота (все прогоны 19.08.2026)

- Стоимость суммарно: **$2.10** (~190 ₽ при лимите ключа 500 ₽/день) — уложились.
- Цепочка run→validate→review→repair→accept работает; журнал полный.
- Главный дефект v1: coder на deepseek-v4-pro не сходится к маркеру DONE за
  40 шагов на задаче такого размера — уходит в полировку и обходные мосты.
  Меры: правила стека в prompts/20 (синхронизированы в мастер-пакет
  `docs/design/specs/agent-forge/prompts/`), glob-форма тестов, запрет
  npm install перенести из промпта в код (v2, AF-10).

### Сводка недели (SESSIONS.md «Что дальше», п.3)

- Стоимость/задача: $0.17–1.11 (после калибровки констант ожидание — ≤$0.30) ·
  доля failed: 2/3 прогонов пилота · DeepSeek vs free-альтернативы: free-вариант
  не прогонялся (OpenRouter недоступен из РФ; provod.ai закрыл потребность).

## Известные ограничения v1 (см. также DECISIONS.md)

- Reviewer получает снапшот записанных файлов, а не `git diff` (AF-02).
- Параллелизма нет — задачи последовательно (осознанно, SPEC §7).
- Docker build в сессии не проверен (daemon остановлен) — проверить
  `docker build -t agent-forge .` при первом удобном случае.

## v1.1 (19.08.2026, после приёмки каркаса atlas)

- `dotnet` добавлен в whitelist run_command; `npx` убран (AF-11).
- Запрет установки зависимостей перенесён из промпта в код — DENY_COMMAND_PATTERNS
  в tools.py (AF-10 закрыт), покрыто tests/test_tools_policy.py.
- Снапшот истории диалога фазы: kill/resume больше не рестартует фазу с чистого
  контекста (AF-08 закрыт), покрыто tests/test_resume_history.py.
- Дочерним командам на Windows прокидываются ProgramFiles-дефолты (NuGet path1).
- Регресс: 27/27 pytest, ruff, mypy — чисто.
