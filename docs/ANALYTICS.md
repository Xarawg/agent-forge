# ANALYTICS — agent-forge: acceptance criteria facts (SPEC.md §6)

Status: assembled in session 1 (19.08.2026). Runs on real DeepSeek model — with owner (SESSIONS.md "After session", items 2–4); here — mock mode and test facts, template for real run data.

## Acceptance Criteria — Status

| # | Criterion (SPEC §6) | Status | Confirmed by |
|---|---|---|---|
| 1 | Pilot task defined in tasks.example.yaml | ✅ | `config/tasks.example.yaml` → `pilot-1-port-validate-canon` (validate_canon.py port to TS) |
| 2 | End-to-end run on DeepSeek, cost ≤ $0.50 | ⏳ awaits owner API key | Chain verified in mock: `run → status → report`, see below |
| 3 | Mock mode FORGE_MOCK=1 without key | ✅ | 22 tests green without key; CI runs pytest with FORGE_MOCK=1 |
| 4 | Repair cycle: ≤3 iterations or failed with journal | ✅ | `tests/test_repair.py`: fix on iteration 1 → done; unfixable → failed after 3, note in journal |
| 5 | Scope control is blocked and logged | ✅ | `tests/test_scope.py` (unit) + `test_mock_run.py::test_scope_violation_logged` (SCOPE_VIOLATION event in events.jsonl) |
| 6 | Tests in one command; Docker image; README local/Docker/Linux | ⚠️ partial | `pytest` — ✅ (22 passed); README — ✅; Dockerfile/compose/CI written, but **image build not verified locally**: Docker Desktop was stopped on session machine |

## Fact: mock run (19.08.2026, FORGE_MOCK=1)

Commands: `forge run --tasks <smoke-tasks.yaml> --target /tmp/forge-target` → `forge report`. Smoke task (1 pc., acceptance on file write):

- Result: task reached `done` (coder → validate → reviewer APPROVE).
- Tokens: 1508 (719 in + 40 out for coder call + repair/review minor — mock counts tokens from message length).
- Cost: $0.0005 at DeepSeek price from `config/models.yaml` (mock uses real price, so report arithmetic is real).
- Repair iterations: 0. Prompt version: `sha256:1a5d877f90e2` (directory not yet under git — fallback triggered, see DECISIONS AF-03).

Gate run (2 tasks, first with `gate: pilot-1`): after first done run paused, second remained `queued`; after `forge accept` + `resume` — reached `done`. Covered by `test_gate_blocks_until_accept`.

## Template for Real Runs (filled by owner, SESSIONS.md item 4)

### Run run-20260819-105828 — 19.08.2026 — provod.ai / deepseek-v4-pro

- Task: pilot-1-port-validate-canon; result: **failed** (25 steps exhausted without DONE).
- Tokens: 387 200 in + 3 270 out. Cost: **$0.1713**.
- Reason: MAX_OUTPUT=4000 truncated source file read (10.7K) — agent spent 25 steps re-reading file in chunks, wrote nothing. Calibration: MAX_OUTPUT→30000, EXCERPT_LIMIT→30000, MAX_AGENT_STEPS→40.

### Run run-20260819-110410 — 19.08.2026 — provod.ai / deepseek-v4-pro (+ flash reviewer)

- Result: **blocked** (per-run cap $0.50 → raised to $2.00; then per-task cap 400K tokens).
- Tokens: 1 739 556 in + 70 103 out. Cost: **$0.8166**.
- Artifact: port written (cli.ts 12.5K, schema-check, tests), CLI runs.
- Model errors: `./x.js` imports instead of `./x.ts` (ERR_MODULE_NOT_FOUND with type stripping); acceptance `node --test <dir>` failed — on owner runtime directory is not scanned, glob needed (AF-09).
- Process at fault too: kill at 300s timeout restarted phase with clean context (AF-08) — model re-read and rewrote files from scratch.

### Run run-20260819-113603 — 19.08.2026 — provod.ai (final)

- Result: agent again failed/blocked on steps and cap; **task accepted manually** (gate #3, `forge accept`) after manual acceptance check.
- Tokens: 2 374 518 in + 95 578 out. Cost: **$1.1139**.
- Prompt violation: coder installed node_modules (tsx/esbuild) and made tsx test bridge despite ban in prompts/20 (AF-10). Artifact cleaned manually: node_modules removed, bridge replaced with glob form, package.json without dependencies.
- Manual acceptance check (owner-orchestrator):
  `node --test "tools-ts/validate-canon/tests/*.test.ts"` → **47/47 pass**;
  `node tools-ts/validate-canon/src/cli.ts canon/` → 200 decisions, 23 modules, 143 events, 90 defs, 301 slots, 4 configs, VALIDATION PASS — identical to python original.

### Pilot Summary (all runs 19.08.2026)

- Total cost: **$2.10** (~190 ₽ at key limit 500 ₽/day) — within budget.
- Chain run→validate→review→repair→accept works; journal is complete.
- Main v1 defect: deepseek-v4-pro coder does not converge to DONE marker in 40 steps for tasks this size — drifts into polishing and workaround bridges.
  Measures: stack rules in prompts/20 (synchronized in master package `docs/design/specs/agent-forge/prompts/`), glob test form, move npm install ban from prompt to code (v2, AF-10).

### Week Summary (SESSIONS.md "What's next", item 3)

- Cost/task: $0.17–1.11 (after constant calibration expectation — ≤$0.30) ·
  failed share: 2/3 pilot runs · DeepSeek vs free alternatives: free option not tested (OpenRouter unavailable from Russia; provod.ai covered need).

## Known v1 Limitations (see also DECISIONS.md)

- Reviewer gets snapshot of written files, not `git diff` (AF-02).
- No parallelism — tasks are sequential (intentional, SPEC §7).
- Docker build not verified in session (daemon stopped) — verify `docker build -t agent-forge .` at first convenience.

## v1.1 (19.08.2026, after product framework acceptance)

- `dotnet` added to run_command whitelist; `npx` removed (AF-11).
- Dependency install prohibition moved from prompt to code — DENY_COMMAND_PATTERNS in tools.py (AF-10 closed), covered by tests/test_tools_policy.py.
- Phase dialogue history snapshot: kill/resume no longer restarts phase with clean context (AF-08 closed), covered by tests/test_resume_history.py.
- Child commands on Windows receive ProgramFiles defaults (NuGet path1).
- Regression: 27/27 pytest, ruff, mypy — clean.
