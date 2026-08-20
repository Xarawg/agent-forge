# SPEC — agent-forge: Agentic Code-Generation Infrastructure

Version 1.1 · Self-specification of the tool (adapted from the original specification package; product/monorepo coupling removed).

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
Per task: collects context (spec excerpt + optional canon snapshot + scope files) → prompt from `prompts/50_task_template.md` → "model ↔ tools" loop until "done" claim or step exhaustion. Agent tools: `read_file`, `write_file`, `list_dir`, `run_command` (whitelist: python, pytest, npm, node, dotnet, ruff, mypy; dependency installation blocked at tool level). Commit tool is not given to the agent — runner commits after reviewer gate. Scope restriction: `write_file` only inside task's `scope_paths`.

### FR-3. Result Validation (Gate #2, Automatic)
After coder: run task's `acceptance` commands (tests/lint/validators — trusted, written by owner) → reviewer role evaluates result against `prompts/30_reviewer.md` checklist → fail goes to repair loop (max N=3 iterations, then task becomes `failed` with journal). Repair agent may finish with `STUCK` (→ failed) or `DISPUTE` (→ blocked: spec contradiction resolved by human, not model).

### FR-4. Execution Control (for Owner)
- Run journal: `runs/<run_id>/events.jsonl` — every event (model call, tokens, command, result).
- Task states: `queued → running → validating → review → done | failed | blocked` (repair iteration = repeated `running`, counter in task state).
- CLI commands: `forge status` (run task table), `forge log <task_id>`, `forge resume <run_id>` (continue after stop), `forge report` (summary: tokens, cost, duration).
- Web UI `forge ui`: kanban board, task event log viewer, run report; read-only `runs/`.
- Human gate #3: merge task branch — only via explicit `forge accept <task_id>`.

### FR-5. Budget Caps
Per-task (max_tokens / max_cost_usd), per-run (max_cost_usd), per-day (max_cost_usd, sum across all `runs/*/events.jsonl` for current UTC day). Exceeding → task `blocked`, reason in journal. Provider limits (RPM/5xx) handled with exponential backoff (`retry` in models.yaml) and `fallback_models` preset fallback.

### FR-6. Provider Configuration
`.env` / environment: `FORGE_PLANNER_BASE_URL/API_KEY/MODEL`, … per role; common fallback `FORGE_BASE_URL` / `FORGE_API_KEY`. Default preset — `config/providers/deepseek.yaml`; selection — `--provider` or `FORGE_PROVIDER`. Mock mode: `FORGE_MOCK=1`.

### FR-7. Reproducibility
Each run records in `run.json`: role models, prompts version (git hash of `prompts/`, outside git — sha256 of content), provider, mock flag. `forge report` includes run cost at config prices.

## 4. Non-Functional Requirements

- NFR-1: Windows 10/11 + Git Bash; no admin rights; Python 3.12+.
- NFR-2: No background daemons — one command = one run; state on disk (process can be killed and `forge resume`; dialogue history snapshots in `tasks/<id>.<phase>.history.json`). Web UI — separate read-only process.
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
