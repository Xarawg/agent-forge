# CONFIGURATION — Complete agent-forge Configuration Reference

How to reuse agent-forge in any other project: environment variables, `config/models.yaml`, provider presets, `tasks.yaml`, prompt library, target repository requirements, platform notes.

Sources of truth in code: `forge/config.py` (env + models.yaml + preset), `forge/models.py` (tasks.yaml schema), `forge/prompts.py` (prompts).

## 1. Environment Variables

All variables are read twice per launch: from `os.environ` (priority) and from `.env` file in agent-forge root (simple `KEY=VALUE` parser, no external deps; `forge/config.py:load_env_file`). `.env` is in `.gitignore`, secrets are not written to run journals (NFR-3).

| Variable | Format | Default | Read in |
|---|---|---|---|
| `FORGE_HOME` | path | parent of `forge/` package (source checkout) | `forge/config.py:forge_root` — root where `config/`, `prompts/`, `runs/`, `.env` are taken from |
| `FORGE_PROVIDER` | path to preset (relative from root) | `config/providers/deepseek.yaml` | `load_config` |
| `FORGE_MOCK` | `1` / `true` / `yes` (case-insensitive) | off | `load_config` → `make_client` (MockClient instead of OpenAI API) |
| `FORGE_MOCK_SCENARIO` | `default` / `rogue` | `default` | `MockClient.scenario` (`forge/llm.py`); `rogue` — coder first tries to write outside scope (scope control test) |
| `FORGE_BASE_URL` | OpenAI-compatible endpoint URL | `provider.base_url` from preset | `load_config`, common fallback for all roles |
| `FORGE_API_KEY` | key string | key from `api_key_env` preset | `load_config`, common fallback for all roles |
| `FORGE_<ROLE>_BASE_URL` | URL | `FORGE_BASE_URL` → preset | `load_config`; ROLE ∈ PLANNER, CODER, REVIEWER, REPAIR |
| `FORGE_<ROLE>_API_KEY` | key string | `FORGE_API_KEY` → `api_key_env` preset | `load_config` |
| `FORGE_<ROLE>_MODEL` | model name | preset `roles.<role>.model` → `models.yaml` | `load_config` |
| `<API_KEY_ENV>` from preset | e.g. `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, `PROVOD_API_KEY` | — | `load_config`, if no `FORGE_*_API_KEY` |

Resolution order for a role (coder example):
`base_url`: `FORGE_CODER_BASE_URL` → `FORGE_BASE_URL` → `provider.base_url` from preset.
`api_key`: `FORGE_CODER_API_KEY` → `FORGE_API_KEY` → value of variable named in preset's `api_key_env`.
`model`: `FORGE_CODER_MODEL` → `roles.coder.model` from preset → `roles.coder.model` from `models.yaml`.

If not mock mode, no key and preset requires `api_key_env` — `load_config` fails with clear error (suggests setting key, `FORGE_MOCK=1`, or ollama preset).

## 2. config/models.yaml

Role model map and budgets. Changing model/price = editing this file, not code.

```yaml
roles:
  planner:                    # planner / coder / reviewer / repair — all four required
    model: deepseek-v4-pro    # default if provider preset does not override role
    max_tokens: 16000         # completion token limit per SINGLE call (truncates large write_file — do not lower)
    temperature: 0.2
    price_per_m_in: 0.435     # USD per 1M input tokens — from provider price list
    price_per_m_out: 0.87     # USD per 1M output tokens
  coder:    { ... }
  reviewer: { ... }
  repair:   { ... }

budgets:                      # defaults; task may override its own (see tasks.yaml)
  per_task_max_tokens: 2000000    # token cap (in+out) per task; against loops, not honest work
  per_run_max_cost_usd: 2.00      # run cost cap; reached — run stops
  per_day_max_cost_usd: 5.00      # cost cap per UTC day across all runs/*/events.jsonl
  repair_max_iterations: 3        # repair loop depth (FR-3)

retry:                        # provider failures: 429/5xx and network errors
  max_attempts: 5
  backoff_seconds: [5, 15, 45, 120, 300]   # pause after i-th attempt; free RPM limits handled here too
```

Prices are declarative: `forge report` and budget caps calculate cost from here (`RoleConfig.cost_usd`). Verify against actual provider price list before running.

## 3. config/providers/*.yaml — Provider Preset

Format (parsed in `forge/config.py:load_config`):

```yaml
provider:
  name: provod                       # human-readable name (in run.json)
  base_url: https://api.provod.ai/v1 # OpenAI-compatible endpoint ({base_url}/chat/completions)
  api_key_env: PROVOD_API_KEY        # env variable name for key; empty/absent = key not needed (ollama)
  api_style: openai-compatible       # informational field, code does not read
  limits:                            # informational block (rpm, daily limits), code does not read
    rpm: null

roles:                               # role model overrides for this provider (optional)
  planner:  { model: deepseek-v4-pro }
  coder:    { model: deepseek-v4-pro }
  reviewer: { model: deepseek-v4-flash }   # reviewer — cheap checklist role
  repair:   { model: deepseek-v4-pro }

fallback_models:                     # fallback on permanent failure of role's primary model
  - deepseek-v4-flash
  - glm-5
```

Existing presets: `deepseek.yaml` (default), `openrouter-free.yaml` (free `:free` models), `ollama.yaml` (local, no key), `provod.yaml`.
Custom provider = new file here + `--provider config/providers/my.yaml` or `FORGE_PROVIDER=...`.

## 4. tasks.yaml — Task Queue

Schema (parsing and validation — `forge/models.py:load_tasks`):

```yaml
package: my-package              # package name (default — file name)
canon_snapshot: canon/decisions.json   # optional: file from target repo, excerpt appended to task prompt

tasks:
  - id: my-task-1                # required; kebab-case: ^[a-z0-9][a-z0-9-]*$; unique
    title: "Short name"          # default — id; shown in status/UI
    spec_ref: "SPEC.md §3.1"     # link to source of truth (informational, goes into prompt)
    scope_paths:                 # required, non-empty: where coder MAY write
      - "src/feature/**"         # gitignore-like masks: ** across /, * inside segment
    depends_on: []               # DAG; cycles and dangling refs are load errors
    acceptance:                  # gate #2 commands; executed by runner (trusted), all must exit 0
      - "cd src/feature && npm test"
    budget:                      # optional: per-task cap overrides (otherwise models.yaml defaults)
      max_tokens: 150000
      max_cost_usd: 0.50
    gate: milestone-1            # optional: milestone label (see below)
```

Semantics:

- **Order** — topological by `depends_on`; ties — file order.
  Tasks run sequentially, no parallelism (NFR-2, free limits).
- **States**: `queued → running → validating → review → done | failed | blocked`.
  Repair iteration — repeated `running`; iteration count — in `tasks/<id>.json`.
  `DISPUTE`/`BLOCKED`/`GAP` from agent → `blocked` (human resolves), `STUCK`/
  step exhaustion/iterations → `failed`.
- **gate**: after a task with `gate` label reaches `done`, run pauses until explicit `forge accept <id>` (human gate #3: accept records acceptance and locally merges `forge/<id>` branch). Continuation — `forge resume <run_id>`.
  Gate holds only `done` tasks: `failed` does not block wave (by design).
  **Owner override**: `forge accept` on a `blocked`/`failed` task marks it `done` with an `override` note in the journal — otherwise a task that hit a cumulative per-task token cap could never recover, since tokens accumulate across resumes.
- **resume**: `forge run`/`resume` skips `done` tasks; dialogue snapshots `tasks/<id>.<phase>.history.json` allow continuing a task killed mid-phase with context and preserved step counter. History snapshots are not task states — `status`/UI/report ignore them.
- **acceptance** is executed by runner as-is (shell, cwd = target repo root, 300s timeout per command) — tool whitelist does NOT apply.

## 5. Onboarding Commands (init / wizard / lint / dry-run / recipes)

Everything here prepares or validates a run **before** money is spent; the draft is always confirmed by a human (gate #1).

- **`forge init [--target DIR] [--profile careful|normal|fast] [--force] [--no-check]`** — prepares a project in one command (`forge/init.py` + `forge/detect.py`): detects the stack (Python/Node/.NET — test commands, package files), inits git if absent, writes a skeleton `tasks.yaml` containing only the checks actually found, and runs a **baseline** (found checks on the untouched repo). Red baseline = honest stop signal: fix the project before agents.
- **`forge wizard [--prompt "..." | --prompt-file F | --recipe NAME] [--profile ...] [--yes] [--out FILE] [--no-check] [--provider P]`** (`forge/wizard.py`) — drafts a complete setup from a plain-words prompt: repo scan → baseline → planner drafts tasks with scopes, acceptance (built from detected checks), profile budgets, and gates → cost forecast → `tasks.wizard.yaml`. If the request is ambiguous, the planner returns a `QUESTIONS:` block and the wizard asks interactively (`--yes` = defaults, non-interactive). Scope entries like `dir/` are normalized to `dir/**`.
- **`forge wizard --recipe NAME`** — deterministic rendering of a recipe from `config/recipes/` (`feature`, `test-coverage`, `docs-sync`): asks the recipe's `questions`, substitutes answers into `{placeholders}`, **no LLM call ($0)**.
- **`forge lint <tasks.yaml>`** (`forge/lint.py`) — pre-flight validation without running: contract errors (schema, DAG cycles, dangling deps) + advisor warnings on frozen acceptance (e.g. test commands that cannot pass at the task's position in the DAG).
- **`forge run --dry-run`** (`forge/dryrun.py`) — cost forecast for the queue from `models.yaml` prices and per-task budgets; nothing executes, no journal is written.
- **Cap profiles** (`forge/profiles.py`): `careful` — task ≤ $0.30, gate after every task (first runs, free models); `normal` — `models.yaml` defaults; `fast` — larger budgets, gates only at the end.
- **UI draft editor**: `forge ui`, then `/wizard?file=<path-to-draft>` — renders the draft as editable task cards; confirming writes the YAML back to the same file. The UI is otherwise read-only.

## 6. prompts/ — Prompt Library

All prompt text — files in `prompts/`, not in code (SPEC §7):

| File | Purpose |
|---|---|
| `00_system.md` | system prompt, shared across all roles |
| `10_planner.md` | planner: SPEC/prompt → tasks.yaml draft (`forge import`, `forge wizard`); may answer with a `QUESTIONS:` block when the request is ambiguous |
| `20_codegen.md` | coder: loop rules, DONE/BLOCKED/GAP markers, commit prohibition |
| `30_reviewer.md` | reviewer: review checklist, verdicts APPROVE/REWORK/REJECT |
| `40_repair.md` | repair: fix per verdict, STUCK/DISPUTE markers |
| `50_task_template.md` | task prompt template (placeholders `{{task.id}}` etc.) |
| `60_target_AGENTS.md` | sample AGENTS.md for target repository |

Versioning: directory under git; library version is recorded in `run.json` (`prompts_version`) as git hash of last commit touching `prompts/` (outside git — sha256 of content; `forge/prompts.py:prompts_version`).

## 7. Pointing forge at Another Project

```bash
pip install -e .            # in agent-forge repository
forge run --tasks path/to/tasks.yaml --target /path/to/target-repo --spec path/to/SPEC.md
```

Zero-YAML alternatives (see §5): `forge wizard --target /path/to/target-repo --prompt "..."` drafts the queue from plain words; `forge init --target ...` prepares a fresh/legacy project (stack detection, git, skeleton, baseline).

- `--tasks` — task queue (see §4). Draft from spec: `forge import --spec SPEC.md --out tasks.draft.yaml`, then edit manually (gate #1).
- `--target` — target repository root (default — current directory). All tool paths and acceptance commands are relative to it.
- Target repo requirements:
  - `AGENTS.md` in root is recommended (sample — `prompts/60_target_AGENTS.md`): stack, test commands, conventions — coder reads it as part of context.
  - Acceptance commands must work from target repo root (tests, linters).
  - git is optional: without repository branching/commit is skipped with journal entry.
    With git — branch `forge/<task-id>` per task, local commit after APPROVE; push is never done (NFR-5).
  - Dependencies are installed by owner in advance: `npm install`/`pip install` etc. are blocked at tool level (AF-10).
- Run and UI are independent: `forge ui` reads `runs/` and works in parallel.

## 8. Platform Notes

- **Windows (reference, NFR-1)**: Git Bash; paths with spaces allowed. Child processes receive `ProgramFiles` / `ProgramFiles(x86)` / `ProgramW6432` defaults — without them NuGet/`dotnet` fail in stripped environments (`forge/tools.py:_WINDOWS_ENV_DEFAULTS`). Commands execute via `shell=True` (cmd semantics for runner and tools).
- **Linux/macOS**: no peculiarities — pure Python, state on disk, no daemons. CI matrix (GitHub Actions) runs ubuntu + windows on Python 3.12/3.13.
- **Docker**: image on `python:3.12-slim`; `runs/` and target repo — volumes (see README). In container `FORGE_HOME` is not needed — root is determined by package.
