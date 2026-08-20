# agent-forge

Controlled, serial LLM code generation over any OpenAI-compatible API — a queue of spec-driven tasks, real test gates, a second-model review, hard budget caps, and a full on-disk audit trail. Русская версия: [README.ru.md](README.ru.md).

## Why

Running "write me a feature" through an LLM is easy. Running *dozens* of such tasks against a real repository without losing control is not. agent-forge exists to make serial LLM codegen governable:

- **Test gates, not trust.** Every task carries `acceptance` commands (real tests/linters) that must exit 0 before anything is considered done.
- **A second model reviews the first.** A reviewer role (different, cheaper model) must approve the result; failures go to a bounded repair loop (≤3 iterations), not to a silent merge.
- **Budget caps in USD.** Per-task, per-run and per-day limits; exceeding them moves the task to `blocked` with the reason in the journal — no runaway bills.
- **DISPUTE instead of hallucination.** When a repair agent cannot reconcile the spec with reality it raises `DISPUTE`/`STUCK` markers and the task stops visibly — the tool never papers over contradictions.
- **Everything on disk.** Each run is a plain directory `runs/<run_id>/` (journal + task states); kill the process any time and `forge resume` continues from history snapshots.

## Features

- Task queue in `tasks.yaml`: DAG with `depends_on`, per-task write scope (`scope_paths`), acceptance commands, per-task budgets, milestone gates.
- Agent loop: coder writes code with `read_file` / `write_file` / `list_dir` / `run_command` tools — scope-controlled, command allowlist, dependency installs blocked at tool level.
- Pipeline per task: coder → acceptance commands → reviewer (second model) → repair loop → `done` / `failed` / `blocked`.
- Human gate: tasks marked with `gate` pause the run until `forge accept <task-id>` (local branch merge).
- Git integration: branch `forge/<task-id>` per task, local commit after reviewer approval; **never pushes**.
- Provider presets (`config/providers/*.yaml`): any OpenAI-compatible endpoint — DeepSeek, OpenRouter free models, local Ollama, etc. Models and prices live in `config/models.yaml`, not in code.
- Mock mode `FORGE_MOCK=1`: the entire cycle without an API key — for CI and development.
- Read-only web UI (`forge ui`): kanban of task states, per-task event log viewer, run cost report.
- Runs are resumable: agent dialogue history is snapshotted after every step; `forge resume <run_id>` picks up where a killed run stopped.

## Quickstart

Requires Python ≥ 3.12.

```bash
pip install -e .

# Full cycle without an API key (mock mode):
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /path/to/any/dir
forge status
forge report
forge log <task-id>
```

For a real run, copy `.env.example` to `.env` and add a provider key (e.g. `DEEPSEEK_API_KEY`), then drop `FORGE_MOCK`:

```bash
forge run --tasks config/tasks.example.yaml --target /path/to/target-repo --spec path/to/SPEC.md
forge accept <task-id>    # human gate: merge the task branch, then
forge resume <run_id>     # continue the run
```

## Configuration

Providers are YAML presets (`config/providers/*.yaml`), models/prices/budgets are in `config/models.yaml`, and everything can be overridden via environment variables (`FORGE_BASE_URL`, `FORGE_API_KEY`, `FORGE_<ROLE>_MODEL`, `FORGE_MOCK`, ...). Full reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md) ([русская версия](docs/CONFIGURATION.ru.md)). The tool specification (FR/NFR) is in [docs/SPEC.md](docs/SPEC.md) ([русская версия](docs/SPEC.ru.md)).

## Web UI

```bash
forge ui            # http://127.0.0.1:8765
forge ui --port 9000
```

Opens a local, offline (zero-CDN, stdlib-only) dashboard that reads `runs/`: a run selector with total cost in the header, a kanban board with columns `queued → running → validating → review → blocked → failed → done`, and clickable task cards that open a side panel with the task's latest journal events (mono-spaced log viewer). A toggle switches the board to a per-task report table (state, tokens, cost, repairs) with totals. The page auto-refreshes every 3 seconds. The UI never mutates run state.

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
