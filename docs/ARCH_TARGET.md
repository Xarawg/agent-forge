# agent-forge v3 target architecture: Docker-served UI, remote-host execution

Date: 2026-08-21 · Vision document · Russian (full) version: [ARCH_TARGET.ru.md](ARCH_TARGET.ru.md)

## Goal

A tool whose UI is served from Docker and which manages code generation end-to-end — up to agents writing code on a remote host while the owner supervises from a browser.

## Core change: control plane / execution plane

- **Control plane** (container on the owner's machine): `forge serve` — REST API + SSE event stream, interactive UI, run scheduler (Runner as a service), LLM clients (provider keys stay here only), `runs/` journals + a rebuildable SQLite index.
- **Execution plane** behind an `Executor` protocol (write/read/list/run_command/acceptance): `host` (current), `docker` (local daemon, network policy), `docker-remote` — the same Docker executor against a remote daemon via `DOCKER_HOST=ssh://…`. Only files and commands travel to the remote host; **LLM keys never leave the control plane**.
- Git under remote execution: task branches/commits live on the remote clone; `forge accept` fetches over SSH and merges `--no-ff` locally (NFR-5 "never push" preserved — fetch is the pull direction).

## Required changes

1. **AF-14 decision**: server mode becomes official alongside one-shot CLI (amends NFR-2); journals on disk remain the source of truth.
2. FastAPI + uvicorn as an **optional** `[server]` extra; core stays stdlib-only.
3. SQLite index over `runs/` (`forge reindex` rebuilds it from journals).
4. Write API: start run, stop/resume, accept; token auth (`FORGE_UI_TOKEN`); SSE replaces 3s polling.
5. Executor refactor of ToolBox; DAG parallelism deferred until server mode stabilizes.
6. Distribution: ghcr.io image + compose + PyPI.

## What self-codegen can carry

~80% of v3 is codegen-tractable (executor mechanics, REST/SSE layer, SQLite index, UI controls) **provided the contracts are specified first** — executor protocol, API surface, server state machine, and network failure semantics are written by the owner, not the model. Waves: A server skeleton → B control API → C remote execution → D state/scale → E distribution. Estimated 12–16 agent-forge tasks, ~$10–15 at DeepSeek prices, 4–5 human gates.

## Explicit non-goals

No k8s, no multi-tenant SaaS, no frontend build step, no custom remote agent daemon while `DOCKER_HOST=ssh` suffices, no removal of the CLI or on-disk journals.

## Owner decisions required before v3

All closed 2026-08-21: AF-14 (server mode official, NFR-2 amended) · AF-15 (FastAPI as optional `[server]` extra) · AF-16 (git fetch+merge accept model) · AF-17 (`DOCKER_HOST=ssh` only; pure-SSH executor deferred).

## Added pillars (2026-08-21)

- **Context & retrieval**: embeddings via an `embedder` role (same OpenAI-compatible mechanism), sqlite-vec single-file store (`runs/context.db`), incremental `forge index`, hybrid coder context (spec → repo-map → top-k vector chunks, all journaled as `phase=context` events), prompt front-matter metadata linked to outcomes via `prompts_version`. Mock embedder keeps CI keyless.
- **Evals**: private per-user harness (AF-13 still stands — nothing public). Golden suites (`evals/suites/*.yaml`) with trap tasks (expect DISPUTE / scope-block, not hallucination), `forge eval --suite`, `forge eval compare` for A/B across models/prompt versions, deterministic mock-suite as CI gate.
- **Observability**: `/metrics` (Prometheus) on `forge serve`, optional OTLP tracing extra (`[otel]`, trace=run, span=task phase), webhook alerts on blocked/failed/budget-cap.
- **Company AI features frame**: agent-forge accelerates building RAG / tool-calling / orchestration features in target products via task-queue templates with acceptance contracts; its own modules serve as a readable reference implementation; `forge eval` doubles as a quality harness for product LLM features.
