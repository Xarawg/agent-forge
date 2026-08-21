# agent-forge gap analysis: done / needed / path

Date: 2026-08-21 · Base: master @ f2b5f0f+ · Russian (full) version: [GAP_ANALYSIS.ru.md](GAP_ANALYSIS.ru.md)

## Done (verified in code)

Core pipeline (coder → acceptance → reviewer → repair ≤3), USD budget caps (task/run/day), human gates, DISPUTE/STUCK markers, on-disk journal + resume, write-scope control, dependency-install block, read-only kanban UI, live CI, honest demo site, documented trust model (SECURITY.md).

## Needed (confirmed gaps)

- **A1** RU site links point to EN docs — need `data-i18n-href`.
- **A2** No `forge init` (project preparation is manual).
- **A3** No step-by-step WORKFLOWS doc for the three flows: prepare project → draft plan → run agents.
- **B1** No cooperative stop (`forge stop` + UI button; today only kill + resume).
- **B2** No GitLab-CI-style stage view per task (phases + per-phase logs in UI).
- **C1** No execution sandbox — commands run on the host. Target: optional `sandbox: docker`, per-run container, target mounted rw, configurable network policy, `docker exec` for agent/acceptance commands, host fallback with journal warning.
- **D1** Reviewer sees file dumps, not `git diff` (AF-02 debt).
- **D2** No repo-map in coder context.
- **E1** No PyPI/release packaging.

## Feasibility

A1–A3, B1, B2, D1 fit the current architecture unchanged (stdlib-only UI constraint is satisfiable). C1 is the only item with an external dependency (Docker on the host) — kept optional, host mode stays default. Out of scope this wave: DAG parallelism (v2), MCP, public benchmark (AF-13), push/PR automation (NFR-5).

## Path

Dogfooding: agent-forge implements it itself on DeepSeek via the queue `config/tasks.v2.yaml`, 4 waves with human gates (t2 → wave-1, t5 → wave-2, t7 → wave-3):

```bash
# raise per_run_max_cost_usd in config/models.yaml 2.00 → ~6.00 first
forge run --tasks config/tasks.v2.yaml --target . --spec docs/GAP_ANALYSIS.ru.md
forge accept t2-site-ru-links && forge resume <run_id>   # per gate
```

Estimated run cost at current DeepSeek prices: ~$3–5.
