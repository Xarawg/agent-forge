# SPEC — agent-forge: Agentic Code-Generation Infrastructure

Version 1.3 · Self-specification of the tool (adapted from the original specification package; product/monorepo coupling removed). v1.2: NFR-2 amended (AF-14 server mode), v2/v3 roadmap references (§7). v1.3: FR-8 onboarding (init/wizard/lint/dry-run/recipes), FR-4 owner override in `forge accept`, `forge report --plain`, wizard draft editor in UI.

## 1. Goal

A tool (`agent-forge`) that the owner runs locally (Windows-first) and which:

1. Reads a specification package (`SPEC.md`) and a task queue `tasks.yaml`.
2. Breaks the package into tasks and drives them through **LLM agents on an OpenAI-compatible API** (presets: DeepSeek direct, free OpenRouter `*:free` models, local via Ollama-compatible endpoint; any other — via a custom preset in `config/providers/`).
3. Controls execution: run journals, task states, budget caps, result validation, human gates between milestones.
4. Works on top of an arbitrary target repository (`--target`), creating a branch per task and local commits; push — only by the owner manually.

NOT a goal: replacing the target repository's CI; acting as an IDE plugin; generating code without a spec (agent-forge always starts from a human-written specification / task queue).

## 2. Roles and Models

| Role | Purpose |
|---|---|
| planner | package → draft task plan (DAG) |
| coder | writes code per task |
| reviewer | reviews result against a checklist |
| repair | fixes based on validator output |

Model map lives in config (`config/models.yaml`), not in code. One provider = base_url + api_key; switching models = editing config. Provider presets — `config/providers/*.yaml`; role models and prices (USD per 1M tokens) — `config/models.yaml`.

## 3. Functional Requirements

### FR-1. Package Import
Reads the package's `SPEC.md` and drafts tasks via the planner role (`forge import`); the owner edits `tasks.yaml` manually before launch (human gate #1). Task format — `config/tasks.example.yaml` (id, title, spec_ref, scope_paths[], depends_on[], acceptance[], budget, gate).

### FR-2. Coder Agent Loop
Per task: collects context (spec excerpt + optional canon snapshot + scope files + repo context) → prompt from `prompts/50_task_template.md` → "model ↔ tools" loop until "done" claim or step exhaustion. Repo context (AF-19): an excerpt of the target repo's `AGENTS.md`, an anti-duplication catalog of all public entity names (from `canon/entities.json`, generated deterministically by `forge map`), and signatures of import-graph neighbors of the task scope. Agent tools: `read_file`, `write_file`, `list_dir`, `run_command` (whitelist: python, pytest, npm, node, dotnet, ruff, mypy; dependency installation blocked at tool level). Commit tool is not given to the agent — runner commits after reviewer gate. Scope restriction: `write_file` only inside task's `scope_paths`.

### FR-3. Result Validation (Gate #2, Automatic)
After coder: run task's `acceptance` commands (tests/lint/validators — trusted, written by owner) → reviewer role evaluates result against `prompts/30_reviewer.md` checklist → fail goes to repair loop (max N=3 iterations, then task becomes `failed` with journal). Repair agent may finish with `STUCK` (→ failed) or `DISPUTE` (→ blocked: spec contradiction resolved by human, not model).

### FR-4. Execution Control (for Owner)
- Run journal: `runs/<run_id>/events.jsonl` — every event (model call, tokens, command, result).
- Task states: `queued → running → validating → review → done | failed | blocked` (repair iteration = repeated `running`, counter in task state).
- CLI commands: `forge status` (run task table), `forge log <task_id>`, `forge resume <run_id>` (continue after stop), `forge report` (summary: tokens, cost, duration; `--plain` — plain-language outcome: done / failed / what next).
- Web UI `forge ui`: kanban board, task event log viewer, run report, wizard-draft editor (`/wizard?file=<draft>`); read-only `runs/` except the draft editor writing back the same draft file.
- Human gate #3: merge task branch — only via explicit `forge accept <task_id>`. Owner override: `forge accept` on a `blocked`/`failed` task marks it `done` with an `override` note (a task that hit a cumulative per-task cap could otherwise never recover).
- DAG safety: a task whose `depends_on` dependency is not `done` never starts — the run stops and waits for the owner to resolve the dependency. `forge status` shows an explicit `⏸ … forge accept <id> && forge resume <run_id>` hint when the run stands at a human gate; `forge report` counts "done N of M" against the full tasks.yaml queue (untouched tasks included as `queued`).

### FR-5. Budget Caps
Per-task (max_tokens / max_cost_usd), per-run (max_cost_usd), per-day (max_cost_usd, sum across all `runs/*/events.jsonl` for current UTC day). Exceeding → task `blocked`, reason in journal. Provider limits (RPM/5xx) handled with exponential backoff (`retry` in models.yaml) and `fallback_models` preset fallback.

### FR-6. Provider Configuration
`.env` / environment: `FORGE_PLANNER_BASE_URL/API_KEY/MODEL`, … per role; common fallback `FORGE_BASE_URL` / `FORGE_API_KEY`. Default preset — `config/providers/deepseek.yaml`; selection — `--provider` or `FORGE_PROVIDER`. Mock mode: `FORGE_MOCK=1`.

### FR-7. Reproducibility
Each run records in `run.json`: role models, prompts version (git hash of `prompts/`, outside git — sha256 of content), provider, mock flag. `forge report` includes run cost at config prices.

### FR-8. Onboarding (Zero-YAML Entry)
The owner can go from "a folder with a project" to a confirmed run without hand-writing `tasks.yaml`:
- `forge init` — target-project preparation: stack detection (`forge/detect.py`: Python/Node/.NET test commands and package files), git init if absent, skeleton `tasks.yaml` containing only the checks actually found, and a **baseline** run of those checks on the untouched repo. A red baseline is a stop signal shown before any model call.
- `forge wizard` — drafts a complete setup (`tasks.wizard.yaml`: tasks, scopes, acceptance from detected checks, profile budgets, gates) from a plain-words `--prompt` / `--prompt-file`; on an ambiguous request the planner answers with a `QUESTIONS:` block and the wizard asks interactively (`--yes` = defaults). Prints a cost forecast before anything runs.
- `forge wizard --recipe NAME` — deterministic rendering of `config/recipes/*.yaml` (`feature`, `test-coverage`, `docs-sync`) with `{placeholder}` substitution; no LLM call.
- Cap profiles (`careful` / `normal` / `fast`) preset per-task budgets and gate density; default is `careful`.
- Pre-flight: `forge lint <tasks.yaml>` (contract errors + frozen-acceptance and acceptance-order advice: a test command must be passable at the task's DAG position) and `forge run --dry-run` (queue cost forecast; nothing executes). The wizard strips not-yet-passable test acceptance from drafts; the planner prompt carries the same rule.
- Every draft is confirmed by a human before launch (gate #1) — in the terminal or as task cards in the UI (`/wizard?file=<draft>`).

## 4. Non-Functional Requirements

- NFR-1: Windows 10/11 + Git Bash; no admin rights; Python 3.12+.
- NFR-2: No background daemons — one command = one run; state on disk (process can be killed and `forge resume`; dialogue history snapshots in `tasks/<id>.<phase>.history.json`). Web UI — separate read-only process. **Amended by AF-14 (2026-08-21):** optional `forge serve` daemon mode is allowed (FastAPI `[server]` extra); on-disk journals remain the single source of truth in both modes. See docs/ARCH_TARGET.ru.md §3.1.
- NFR-3: Secrets only in `.env` (in .gitignore); logs do not contain keys.
- NFR-4: Pilot task cost on paid model ≤ $0.50; on free models — $0 (RPM limits handled by backoff).
- NFR-5: agent-forge never pushes to remote git; branch + local commit — yes, push — no.

## 5. Data Model

```
tasks.yaml        — package task queue (see config/tasks.example.yaml)
runs/<run_id>/    — run.json (metadata), events.jsonl (journal), tasks/<id>.json (state, repair iterations)
prompts/          — prompt library (versioned by git)
config/           — models.yaml, providers/*.yaml, tasks.example.yaml
```

Journal event: `{ts, run_id, task_id, phase, role, model, tokens_in, tokens_out, cost_usd, command?, exit_code?, note}`.

## 6. Acceptance Criteria

1. End-to-end run on real provider: task reaches `done` or meaningful `failed`; `forge status`/`report` show progress; cost within cap.
2. Mock mode (`FORGE_MOCK=1`): full cycle without API key — for CI and agent-forge development.
3. Repair loop: intentionally broken acceptance fixed in ≤3 iterations or task becomes `failed` with clear journal.
4. Scope control: coder attempt to write outside `scope_paths` is blocked and logged.
5. agent-forge tests run in one command; Docker image builds; README covers local/Docker/Linux.

## 7. Limitations and Anti-Patterns

- Do not give coder role write access to `canon/` (`canon/` in target repo — always read-only for agent; code generation reads canon, owner edits it only).
- Do not invent prompts in code — all prompt text lives in `prompts/` (versioned, reviewed).
- Do not hide raw model responses — events.jsonl is complete (except secrets).
- Do not add parallelism in v1: tasks run sequentially (free limits); parallelism — NFR for v2.
  **Roadmap (2026-08-21):** v2 queue — `config/tasks.v2.yaml` (gap-fix wave per docs/GAP_ANALYSIS.ru.md); v3 queue — `config/tasks.v3.yaml` (target architecture per docs/ARCH_TARGET.ru.md: server mode, executor plane incl. remote docker, context/evals/observability). DAG parallelism inside a run is scheduled for v3 wave D (multi-run first); human gates between waves remain mandatory.
