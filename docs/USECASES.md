# 10 field scenarios for agent-forge

Each scenario is a real way of working with agentic code generation: from greenfield
by specification to integration into legacy and someone else's vibe-code. The chain shows
which forge commands a person issues and in what order; agents do everything else
behind the gates. Русская версия: [USECASES.ru.md](USECASES.ru.md).

## 1. Greenfield: new service from specification to code

**Context.** A startup writes a URL-shortener from scratch. First a person writes SPEC.md
(API, storage, acceptance criteria), then the package goes to agents.

```bash
forge init --target ./shortener                       # git, skeleton, baseline
forge import --spec ./shortener/SPEC.md --out tasks.draft.yaml   # planner: SPEC → DAG
forge lint tasks.draft.yaml                           # контракт + порядок acceptance
forge run --tasks tasks.draft.yaml --target ./shortener --spec ./shortener/SPEC.md --dry-run
forge run --tasks tasks.draft.yaml --target ./shortener --spec ./shortener/SPEC.md
forge accept models-layer && forge resume run-…       # гейт после каркаса
forge report --plain                                  # итог простым языком
```

Tasks go by DAG: models → storage → API → tests → docs. Tests are a separate task
after code (prompts/10, item 5), acceptance for each task is passed at its
position. Each `gate` is a point where a person reviews the diff.

## 2. Contract-first: from OpenAPI contract to implementation

**Context.** The team agreed on `openapi.yaml` with the frontend; the backend must
comply with it. The contract is the source of truth; acceptance is contract tests.

```bash
forge wizard --target ./backend \
  --prompt "реализуй эндпоинты по openapi.yaml; acceptance: schemathesis run openapi.yaml"
# wizard находит проверки, чертит задачу на группу эндпоинтов
forge run --tasks ./backend/tasks.wizard.yaml --target ./backend
# reviewer проверяет: код не выходит за scope, контрактные тесты зелёные
forge accept users-endpoints && forge resume run-…
```

Each task's scope is its own package of endpoints; `canon/` with openapi.yaml is
read-only for the coder — the contract cannot be “tweaked to fit the code”.

## 3. New microservice in an existing monorepo with canon

**Context.** The monorepo has `canon/decisions.json` (ADR, conventions). A new
service must follow them, not invent its own.

```bash
forge wizard --target ./monorepo --prompt "новый сервис billing по canon-решениям"
# в tasks.wizard.yaml добавляем вручную: canon_snapshot: canon/decisions.json
forge lint ./monorepo/tasks.wizard.yaml
forge run --tasks ./monorepo/tasks.wizard.yaml --target ./monorepo
```

`canon_snapshot` is attached to the prompt of each task; any attempt by the coder
to write to `canon/` is blocked by the tool and logged as SCOPE_VIOLATION.

## 4. Legacy without tests: first groundwork, then agents

**Context.** An 8-year-old Django project, no tests, “works — don’t touch”.
The first pass of agents is not features, but testability.

```bash
forge init --target ./legacy-shop          # baseline КРАСНЫЙ: проверок нет
forge wizard --target ./legacy-shop --recipe test-coverage
# ? модуль → src/payments · команда → python -m pytest -q   (без LLM, $0)
forge run --tasks ./legacy-shop/tasks.wizard.yaml --target ./legacy-shop
forge accept cover-payments && forge resume run-…
```

Baseline honestly says “there is nothing to check with” before spending on
models. The first task writes tests against existing code — acceptance runs the
new tests against the old code. Only after that does refactoring make sense.

## 5. Legacy migration: port by module with parity

**Context.** Porting a validator from Python to TypeScript; the requirement is
bit-for-bit behavioral parity. One module = one task.

```bash
# tasks.yaml руками: acceptance — прогон golden-наборов через обе реализации
forge lint tools/migration.tasks.yaml
forge run --tasks tools/migration.tasks.yaml --target ./repo --dry-run   # прогноз
forge run --tasks tools/migration.tasks.yaml --target ./repo
```

Acceptance compares the output of the old and new implementations on golden
data: parity is proven by a test, not by model assurances. A red run → repair
cycle (≤3 iterations), then `failed` with a log, not a silent merge.

## 6. Brownfield with documentation: AGENTS.md already exists

**Context.** The repository maintains AGENTS.md (stack, commands, conventions)
and docs/SPEC.md. The tool reads what is already written.

```bash
forge import --spec ./repo/docs/SPEC.md --out tasks.draft.yaml
forge lint tasks.draft.yaml
forge run --tasks tasks.draft.yaml --target ./repo --spec ./repo/docs/SPEC.md
```

AGENTS.md from the target root is included in the coder’s context — it writes
according to the project’s conventions, not “the average across GitHub”.
`--spec` attaches an excerpt of the spec to each task prompt.

## 7. Vibe-code: a project generated “on the knee” by another AI

**Context.** A prototype from another AI tool: the code works, but there is no
structure, no tests, checks do not run. The task is to turn it into something
maintainable.

```bash
forge init --target ./vibe-app --profile careful     # baseline красный — честный стоп
# человек сначала чинит запуск проверок (один раз, руками)
forge wizard --target ./vibe-app \
  --prompt "разбей god-object app.py на модули, сверху pytest-тесты" --profile careful
forge run --tasks ./vibe-app/tasks.wizard.yaml --target ./vibe-app
# careful: кап $0.30/задача и гейт после каждой — полный контроль над хаосом
forge accept split-config && forge resume run-…
```

Wizard does not invent checks: it takes only the ones found in the repo.
Acceptance that cannot pass yet (pytest before tests exist) is dropped from the
draft with a warning — DISPUTE does not happen out of nowhere.

## 8. Someone else’s AI-driven practice: specs from spec-kit / BMAD

**Context.** The project was run under another methodology: a `specs/` directory
with someone else’s feature format, partially implemented, architecture
partially broken.

```bash
forge import --spec ./repo/specs/004-export/SPEC.md --out tasks.draft.yaml
# гейт №1: человек вычитывает черновик — planner честно выносит противоречия
forge lint tasks.draft.yaml        # предупредит о непроходимом acceptance
forge run --tasks tasks.draft.yaml --target ./repo
```

If the spec diverges from the code, the repair agent does not “guess”: a
DISPUTE marker → task in `blocked`, the decision is made by a human
(`forge accept` as override or spec edit). Contradictions are not hidden — this
is a principle of the tool.

## 9. Multi-repo: one change in five services

**Context.** Changing the auth token format affects 5 repositories. The same
queue is run against each — separate branches, logs, cost.

```bash
for repo in api gateway billing notify web; do
  forge run --tasks token-v2.tasks.yaml --target ./$repo
done
forge report run-…    # по каждому прогону: стоимость, состояние, repair'ы
forge ui              # канбан всех прогонов разом, только чтение
```

No push: branches `forge/<task-id>` and commits are local; the owner publishes
them (NFR-5). The per-day cap is summed across all runs of the day — the budget
won’t drift.

## 10. Documentation drift after AI sprints

**Context.** Several code-generation sprints — README and ANALYTICS have fallen
behind the code. The docs-sync recipe restores sync without invoking the
planner.

```bash
forge wizard --target ./repo --recipe docs-sync       # детерминированно, $0
forge run --tasks ./repo/tasks.wizard.yaml --target ./repo
forge report --plain   # «Сделано 2 из 2: README, ANALYTICS — $0.07»
forge ui               # визуальный контроль: что когда починялось
```

Acceptance for docs tasks is not tests but owner checks (markdown linter,
running examples from README). The tool does not care what gates a task — as
long as the command is honest and turns green.

## General skeleton of any scenario

1. **Preparation**: `forge init` / `forge wizard` / `forge import` → draft, gate #1 — human.
2. **Preflight**: `forge lint` + `--dry-run` → contract, acceptance order, price forecast.
3. **Run**: `forge run` → coder → acceptance → reviewer → repair, budget caps at every step.
4. **Gates**: `forge accept` / `forge resume` → human between milestones; blocked/failed — owner override.
5. **Control**: `forge status` / `forge log` / `forge report --plain` / `forge ui` → everything on disk in `runs/`.
