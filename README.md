# agent-forge

Controlled, serial LLM code generation over any OpenAI-compatible API — a queue of spec-driven tasks, real test gates, a second-model review, hard budget caps, and a full on-disk audit trail. Русская версия: [README.ru.md](README.ru.md).

## Why

Running "write me a feature" through an LLM is easy. Running *dozens* of such tasks against a real repository without losing control is not. agent-forge exists to make serial LLM codegen governable:

- **Test gates, not trust.** Every task carries `acceptance` commands (real tests/linters) that must exit 0 before anything is considered done.
- **A second model reviews the first.** A reviewer role (different, cheaper model) must approve the result; failures go to a bounded repair loop (≤3 iterations), not to a silent merge.
- **Budget caps in USD.** Per-task, per-run and per-day limits; exceeding them moves the task to `blocked` with the reason in the journal — no runaway bills.
- **DISPUTE instead of hallucination.** When a repair agent cannot reconcile the spec with reality it raises `DISPUTE`/`STUCK` markers and the task stops visibly — the tool never papers over contradictions.
- **Everything on disk.** Each run is a plain directory `runs/<run_id>/` (journal + task states); kill the process any time and `forge resume` continues from history snapshots.
- **You don't have to write YAML.** `forge init` and `forge wizard` scan the target project, find its real checks, and draft the whole setup — tasks, acceptance, budgets — for you to confirm.

## Features

- **Onboarding for any project state** — from an empty folder to a legacy monorepo:
  - `forge init` — detects the stack (Python/Node/.NET), inits git if needed, writes a `tasks.yaml` skeleton with the checks it actually found, runs a baseline (red baseline = honest stop before any model call).
  - `forge wizard --prompt "..."` — scans the repo, runs baseline checks, asks clarifying questions when the request is ambiguous (QUESTIONS protocol), and drafts a complete `tasks.wizard.yaml`: tasks, scopes, acceptance, budgets, gates — plus a cost forecast. Acceptance that cannot pass yet (a test command before any test-writing task, in a repo without tests) is stripped with a visible warning. You confirm the draft (human gate #1) and run it.
  - `forge wizard --recipe feature` — ready-made recipes from `config/recipes/` (`feature`, `test-coverage`, `docs-sync`) with no LLM call at all ($0).
  - `forge import --spec SPEC.md` — drafts a task queue from an existing specification via the planner role.
- **Task queue in `tasks.yaml`**: DAG with `depends_on`, per-task write scope (`scope_paths`), acceptance commands, per-task budgets, milestone gates.
- **Agent loop**: coder writes code with `read_file` / `write_file` / `list_dir` / `run_command` tools — scope-controlled, command allowlist, dependency installs blocked at tool level.
- **Pipeline per task**: coder → acceptance commands → reviewer (second model) → repair loop → `done` / `failed` / `blocked`.
- **Human gate**: tasks marked with `gate` pause the run until `forge accept <task-id>` (records acceptance, merges the local branch). A `blocked`/`failed` task can also be accepted manually as an explicit owner override.
- **Pre-flight tooling**: `forge run --dry-run` (cost forecast without starting anything) and `forge lint <tasks.yaml>` (contract validation + acceptance advice: tests frozen outside coder scope, and every test command passable at the task's DAG position — before you spend a cent).
- **Git integration**: branch `forge/<task-id>` per task, local commit after reviewer approval; **never pushes**. Works fine on non-git targets too (branching is skipped with a journal entry).
- **Provider presets** (`config/providers/*.yaml`): any OpenAI-compatible endpoint — DeepSeek, OpenRouter free models, local Ollama, etc. Models and prices live in `config/models.yaml`, not in code.
- **Mock mode** `FORGE_MOCK=1`: the entire cycle without an API key — for CI and development.
- **Read-only web UI** (`forge ui`): kanban of task states, per-task event log viewer, run cost report, and a browser form (`/wizard?file=<draft>`) to edit a wizard draft as task cards.
- **Resumable runs**: agent dialogue history is snapshotted after every step; `forge resume <run_id>` picks up where a killed run stopped.
- **Plain-language reporting**: `forge report --plain` — what got done, what failed, what to do next, no YAML archaeology required.

## Installation

Requires Python ≥ 3.12 (Windows + Git Bash is the reference platform; Linux/macOS work identically).

```bash
git clone https://github.com/Xarawg/agent-forge.git
cd agent-forge
python -m venv .venv
source .venv/Scripts/activate     # Git Bash on Windows; .venv/bin/activate on Linux/macOS
pip install -e .
```

Optional, for a real (non-mock) run — copy `.env.example` to `.env` and add a provider key:

```bash
cp .env.example .env
# edit .env: DEEPSEEK_API_KEY=sk-...   (or OPENROUTER_API_KEY, or none for Ollama)
```

Verify the install without any API key:

```bash
FORGE_MOCK=1 pytest -q
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /tmp/demo
forge status && forge report --plain
```

## Use Cases — From Zero to a Working Run

All commands below run from the agent-forge checkout; `--target` points at *your* project.

### A. New project (empty folder, no code, no specs)

```bash
forge init --target /path/to/new-project
forge wizard --target /path/to/new-project --prompt "CLI calculator: package calc with add(a,b), python -m calc 2 3, pytest tests"
# → /path/to/new-project/tasks.wizard.yaml — review the draft (gate #1), then:
forge run --tasks /path/to/new-project/tasks.wizard.yaml --target /path/to/new-project
forge report --plain
```

The wizard prints a cost forecast before anything runs. With the default `careful` profile every task pauses for `forge accept <task-id>` — you inspect the result, accept, then `forge resume <run_id>`.

### B. Legacy project (lots of code, no spec, no AGENTS.md)

The wizard scans the tree, detects the stack and existing test commands, runs them as a baseline, and drafts tasks that fit the project's real conventions. Start with a test-coverage recipe if you want the safest first run:

```bash
forge wizard --target /path/to/legacy --recipe test-coverage      # no LLM call, $0
forge run --tasks /path/to/legacy/tasks.wizard.yaml --target /path/to/legacy
```

If the baseline is already red, `forge init`/wizard say so and stop — fix the project first, agents second.

### C. Project with AGENTS.md / SPEC.md and other docs

agent-forge reads what's already there: `AGENTS.md` in the target root goes into the coder's context (stack, conventions, test commands — sample in `prompts/60_target_AGENTS.md`), and a spec can drive the whole queue:

```bash
forge import --spec /path/to/project/SPEC.md --out tasks.draft.yaml   # planner draft (gate #1)
forge lint tasks.draft.yaml                                           # contract + acceptance advice
forge run --tasks tasks.draft.yaml --target /path/to/project --spec /path/to/project/SPEC.md
```

`--spec` attaches an excerpt of the spec to every task prompt; `canon_snapshot` in `tasks.yaml` pins a canonical file (e.g. `canon/decisions.json`) the same way. `canon/` is always read-only for agents.

### D. Hands-on: your own tasks.yaml

Write or edit the queue manually (schema: [docs/CONFIGURATION.md](docs/CONFIGURATION.md) §4), then:

```bash
forge lint tasks.yaml                 # validate before spending
forge run --tasks tasks.yaml --dry-run   # cost forecast, nothing executes
forge run --tasks tasks.yaml --target /path/to/repo
forge status                          # task table
forge log <task-id>                   # full event journal of one task
forge accept <task-id>                # human gate #3 (also: manual override for blocked/failed)
forge resume <run_id>                 # continue after a stop or a gate
forge report --plain                  # plain-language summary
forge ui                              # kanban dashboard on http://127.0.0.1:8765
```

## Command Reference

| Command | Purpose |
|---|---|
| `forge init [--target DIR] [--profile careful\|normal\|fast] [--force] [--no-check]` | Prepare a project: stack detection, git init, skeleton `tasks.yaml`, baseline checks |
| `forge wizard --prompt "..." [--recipe NAME] [--profile ...] [--yes] [--out FILE] [--no-check]` | Draft a full setup (tasks/acceptance/budgets/gates) from a plain-words prompt, a prompt file, or a recipe |
| `forge import --spec SPEC.md [--out FILE]` | Draft `tasks.yaml` from an existing specification via the planner |
| `forge lint <tasks.yaml>` | Pre-flight validation: contract errors + acceptance advice (frozen scope, DAG-order passability) |
| `forge run --tasks F [--target DIR] [--spec SPEC.md] [--dry-run] [--provider PRESET]` | Run the queue; `--dry-run` prints a cost forecast and executes nothing |
| `forge resume <run_id> [--target DIR]` | Continue a stopped/paused run from on-disk snapshots |
| `forge status [run_id]` | Task table: state, tokens, cost, repairs, notes |
| `forge log <task-id> [--run ID]` | Full event journal of one task |
| `forge report [run_id] [--plain]` | Cost/token summary; `--plain` — human-readable outcome and next steps |
| `forge accept <task-id> [--run ID] [--target DIR]` | Human gate #3: accept a done task (merge branch); also a manual override for `blocked`/`failed` |
| `forge ui [--port 8765]` | Read-only web dashboard: kanban, log viewer, cost report, wizard-draft editor (`/wizard?file=...`) |

Cap profiles for `init`/`wizard`: `careful` (task ≤ $0.30, a gate after every task — first runs and free models), `normal` (models.yaml defaults), `fast` (larger tasks, rare gates).

## Configuration

Providers are YAML presets (`config/providers/*.yaml`), models/prices/budgets are in `config/models.yaml`, and everything can be overridden via environment variables (`FORGE_BASE_URL`, `FORGE_API_KEY`, `FORGE_<ROLE>_MODEL`, `FORGE_MOCK`, ...). Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md) ([русская версия](docs/CONFIGURATION.ru.md)). The tool specification (FR/NFR) is in [docs/SPEC.md](docs/SPEC.md) ([русская версия](docs/SPEC.ru.md)).

## Web UI

```bash
forge ui            # http://127.0.0.1:8765
forge ui --port 9000
```

Opens a local, offline (zero-CDN, stdlib-only) dashboard that reads `runs/`: a run selector with total cost in the header, a kanban board with columns `queued → running → validating → review → blocked → failed → done`, and clickable task cards that open a side panel with the task's latest journal events. A toggle switches the board to a per-task report table (state, tokens, cost, repairs) with totals. `/wizard?file=<draft>` renders a wizard draft as editable task cards (the confirmed YAML is written back to the same file). The page auto-refreshes every 3 seconds and never mutates run state.

## Docker

```bash
docker build -t agent-forge .
docker run --rm --env-file .env \
  -v ${PWD}/runs:/app/runs -v /path/to/target-repo:/target \
  agent-forge run --tasks config/tasks.example.yaml --target /target
```

or via compose (`export FORGE_TARGET_REPO=/path/to/target-repo`, then `docker compose run --rm forge run ...`; `docker compose run --rm test` runs pytest inside the image).

## Development

```bash
pip install -e ".[dev]"
pytest -q            # all tests run in mock mode, no API key needed
ruff check .
mypy --strict forge/
```

CI: GitHub Actions (`.github/workflows/ci.yml`, ubuntu × windows, Python 3.12/3.13) and GitLab CI (`.gitlab-ci.yml`).

## Security

Scope control and the command allowlist are guardrails against model mistakes, **not a sandbox** — allowlisted commands (`python`, `npm`, …) can execute arbitrary code, and `acceptance` commands are trusted owner shell. Exact boundaries and recommendations: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2026 agent-forge contributors.
