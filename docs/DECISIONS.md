# DECISIONS — agent-forge build decisions and deviations (session 1)

All deviations from SPEC.md v1.0 are recorded here and in ANALYTICS.md (not silently).

## AF-01. Agent has no `git_commit` tool

**Spec:** §FR-2 lists `git_commit` among agent tools.
**Conflict:** `prompts/20_codegen.md` forbids coder from committing («commit is done by agent-forge after reviewer gate»).
**Decision:** tool is not given to agent (not in TOOL_SCHEMAS); local commit is done by runner after reviewer APPROVE. Prompt has priority — it is newer in intent and safer (commit after gate, not before).

## AF-02. "Diff" for reviewer — snapshot of written files

**Spec:** §FR-3 — "reviewer role evaluates diff".
**Decision v1:** runner tracks files written via `write_file` and passes their content (up to 3000 chars per file) plus acceptance output to reviewer. True `git diff` is impossible when target is not a git repository (and v1 must work in this case). For git target, content of written files is equivalent to diff of new files; edits to existing files are visible without old version. **Debt v2:** when git is present — attach `git diff` of task branch.

## AF-03. Prompt version: git hash with sha256 fallback

**Spec:** §FR-7 — "prompt version (git hash prompts/)".
**Decision:** if agent-forge directory is a git repository, use `git log -1 --format=%H -- prompts/`; otherwise — sha256 of concatenated `prompts/*.md` files (deterministic, reproducible). Fallback is needed because repository is assembled before first commit, and tests and Docker must always work.

## AF-04. Repair state = repeated `running`

**Spec:** §FR-4 lists states `queued → running → validating → review → done | failed | blocked`; no separate repair state.
**Decision:** repair iteration moves task back to `running` with note `repair iteration N/3`; iteration count is stored in `tasks/<id>.json` (`repair_iterations`) and visible in `forge status`/`report`.

## AF-05. Acceptance commands outside whitelist

**Spec:** §FR-2 — whitelist for agent's `run_command` (tests, linter, validate_canon).
**Decision:** whitelist (`python, pytest, npm, npx, node, ruff, mypy`) applies only to agent tool. Acceptance commands from tasks.yaml are written by owner (trusted) — runner executes them as-is, with 300s timeout.

## AF-06. Per-day cap is calculated from runs/ journals

**Spec:** §FR-5 — caps per-task / per-run / per-day.
**Decision:** no separate ledger; per-day — sum of `cost_usd` across all `runs/*/events.jsonl` for UTC day. Simple and sufficient for a single-user tool; journals are the single source of truth on costs.

## AF-07. Repository Location

Tool lives in `big fantasy/agent-forge/` — next to target monorepo (directories `canon/`, `tools/`, `docs/design/specs/` accessible as `..`). Specification package (`docs/design/specs/agent-forge/`) remains untouched.

## AF-08. Resume restarts phase with clean context (pilot fact)

Killed by timeout run resumes from phase start: agent dialogue is not restored, model re-reads files and redoes work. Restart cost — 25–50K tokens per call. Operational rule: do not kill run mid-phase; long runs — via `nohup ... &` with journal polling.
**Debt v2:** save dialogue history in `tasks/<id>.json` and restore.

## AF-09. `node --test <dir>` does not work on owner runtime

Node 24.15.0 from kimi-desktop runtime: directory argument fails with MODULE_NOT_FOUND (directory resolves as entry point). Working form — glob: `node --test "tests/*.test.ts"` (Node expands glob itself). Hardcoded in prompts/20_codegen.md (both copies: repo + master package).

## AF-10. `npm install` prohibition in prompt is insufficient

Pilot coder installed node_modules (tsx/esbuild) and wrote tsx test bridge despite explicit ban in prompts/20 — whitelist `run_command` contains npm, and model took familiar path. Prompt is not a boundary. **Debt v2:** ban `npm install`/`npx <package>` at tool level (block as SCOPE_VIOLATION) or explicit dependency allowance in task contract. Stack rule (`.ts` imports, erasable syntax only) nevertheless stayed in prompt — it worked: final port is clean.

## AF-11. v1.1: dotnet in whitelist, ProgramFiles in child env

**Product framework acceptance fact (19.08.2026):** product module tasks require `dotnet build/test` — added to COMMAND_ALLOWLIST; `npx` removed from whitelist (executes arbitrary packages = dependency ban bypass). Child commands on Windows receive `ProgramFiles`/`ProgramFiles(x86)`/`ProgramW6432` defaults: without them NuGet fails with «Value cannot be null (Parameter 'path1')» in stripped environments (found during product framework acceptance).

## AF-12. v1.1: phase dialogue history snapshot (closes AF-08 debt)

`run_tool_agent` writes `runs/<run>/tasks/<id>.<phase>.history.json` after each step; killed run leaves snapshot, resume continues phase with context and preserved step counter. On normal phase completion (any marker, including STEPS_EXHAUSTED) snapshot is deleted — re-running task starts with clean dialogue and fresh step budget. Covered by tests/test_resume_history.py.

## 20.08.2026 — calibration from run-20260820-080204 (waves 1–2 of product modules)

1. **max_tokens coder/repair 8000 → 32000** (config/models.yaml). Symptom: modular *.cs (12–14 KB) were truncated mid-file, reviewer caught invalid diff 3 iterations in a row (mod-world-time → failed). Limit was cutting write_file with large content.
2. **Acceptance without `--filter "FullyQualifiedName~..."`** (in module task config): filter gave «No test matches» when running at solution level (projects without matches), reviewer treated as red gate. Now full `cd server && dotnet test` — seconds slower, but no false negatives.
3. Gates hold only state=done — failed tasks do not block wave (by design), so wave 2 started with failed wave 1. Fixed by restart: done are skipped, failed are replayed; forge/<id> branches are recreated via `checkout -B`, no manual cleanup needed.

## AF-13. No public cost/quality benchmark

**Context:** competitive analysis (docs/COMPETITIVE_ANALYSIS.md) recommended a public mini-benchmark «model × cost × % done» as evidence base.
**Decision (owner, 2026-08-20):** rejected. agent-forge is provider-agnostic: the owner's runs go through their provider with their prices, other users bring their own provider keys and models — owner's cost figures do not transfer and would mislead. Cost accounting stays per-user via `config/models.yaml` prices and `forge report`; reproducibility evidence is the on-disk journal format and mock mode, not a published leaderboard.

## AF-14. Server mode is official (amends NFR-2)

**Context:** v3 target architecture (docs/ARCH_TARGET.ru.md) requires a UI served from Docker managing runs interactively.
**Decision (owner, 2026-08-21, «все дефолты ок»):** two modes coexist. CLI one-shot stays forever (CI, development, kill-safe). `forge serve` is an optional daemon; on-disk journals (`runs/`) remain the single source of truth in both modes — the server survives restarts by reading them. NFR-2 amended accordingly.

## AF-15. FastAPI as optional `[server]` extra

**Decision (owner, 2026-08-21):** approved. Core stays stdlib-only (NFR-1); server mode uses FastAPI + uvicorn as an optional extra `pip install agent-forge[server]`. UI static remains build-step-free.

## AF-16. Git model for remote execution: fetch + merge on accept

**Decision (owner, 2026-08-21):** approved. Under remote execution the target clone lives on the remote host; task branches/commits are created there; `forge accept` fetches the task branch over SSH and merges `--no-ff` locally. NFR-5 («never push») preserved — fetch is the pull direction.

## AF-17. Remote transport: `DOCKER_HOST=ssh://` only (v3)

**Decision (owner, 2026-08-21):** remote execution reuses the Docker executor against a remote daemon via `DOCKER_HOST=ssh://user@host` — one sandbox code path, local or remote. A pure-SSH executor (no Docker on target host) is deferred until a real need appears. LLM keys never leave the control plane; only files and commands travel to the remote host.
