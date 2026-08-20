# ARCHITECTURE — agent-forge

Version 0.1 · 19.08.2026 · Per specification `docs/design/specs/agent-forge/SPEC.md` v1.0.

## Overview

One CLI (`forge`), one command = one run (NFR-2). State is entirely on disk in `runs/<run_id>/` — the process can be killed and continued with `forge resume`. No parallelism: tasks run sequentially in DAG topological order (§7 — free provider limits).

## Run Flow (`forge run`)

```
tasks.yaml ──load_tasks──► DAG (topo_order)
        │
        ▼ for each task
   ┌─────────────┐   blocked  ◄── budget caps (per-task/run/day)
   │ gate check  │── pause ◄── previous gated task done and not accepted
   └─────────────┘
        ▼ running
   coder loop (run_tool_agent): model ↔ tools(read/write/list/run_command)
        ▼ marker DONE / BLOCKED / GAP / STEPS_EXHAUSTED
   validating: acceptance commands (trusted, from tasks.yaml)
        ▼
   review: reviewer role via prompts/30 checklist (no tools)
        ▼ APPROVE+green ──► git commit ──► done
        ▼ REWORK/red ──► repair loop (≤3 iterations) ──► failed
        ▼ REJECT ──► failed
```

## `forge/` Modules

| Module | Responsibility |
|---|---|
| `cli.py` | argparse: run / resume / status / log / report / accept / import |
| `config.py` | models.yaml + provider preset + .env; builds RoleConfig per role |
| `models.py` | tasks.yaml: parsing, validation, DAG, task states |
| `llm.py` | `LLMClient` protocol; `OpenAIClient` (retry/backoff, fallback models); `MockClient` |
| `tools.py` | Agent tools; scope control; command whitelist |
| `agents.py` | "model ↔ tools" loop; single-step reviewer; markers |
| `runner.py` | Phase orchestration, budgets, gates, git |
| `journal.py` | run.json, events.jsonl, tasks/<id>.json |
| `report.py` | status/report summaries from journal |
| `prompts.py` | Prompt loading/rendering; library version (git hash / sha256) |

## Key Mechanisms

### Scope Control (§FR-2, §6.5, §7)
`ToolBox.write_file` normalizes path, forbids escaping target repo root (`..`), always forbids `canon/`, then matches against gitignore-like `scope_paths` masks (`**` — across separators, `*` — inside segment). Violation is returned to model as `ERROR:` and logged with `SCOPE_VIOLATION` tag.

### Budgets (§FR-5)
Checked before task start and before each repair iteration. per-day cap is sum of `cost_usd` across all `runs/*/events.jsonl` for current UTC day. Exceeding → task `blocked`, reason in journal and `forge status`.

### Reproducibility (§FR-7)
`run.json` records: provider, mock flag, role models, prompts version (git hash of last commit touching `prompts/`; outside git — sha256 of content). `forge report` calculates cost from `config/models.yaml` prices.

### Mock Mode (§6.3)
`MockClient` — deterministic role-based stub: coder writes `<scope>/mock_output.md` and finishes DONE; repair writes `mock_state.txt` with `iteration-N`; reviewer — APPROVE on green acceptance, otherwise REWORK; planner — valid YAML draft. `FORGE_MOCK_SCENARIO=rogue` tests scope control. Tokens counted from message length, cost — from config prices, so reports and caps run for real.

### Git (§1.4, NFR-5)
If target is a git repository: branch `forge/<task-id>` per task, local commit of written files after APPROVE. `forge accept` merges branch locally (`--no-ff`). Push is absent as a class. If target is not a git repository — phase is skipped with journal entry.

## Journal (§5)

Event: `{ts, run_id, task_id, phase, role, model, tokens_in, tokens_out, cost_usd, command?, exit_code?, note}`. Phases: `run`, `gate`, `state`, `git`, `coder`, `repair`, `validate`, `review`, `plan`, `budget`. Raw model responses (up to 2000 chars) — in `note` of call events; secrets are not written to journal (keys live only in `.env` and env vars, NFR-3).
