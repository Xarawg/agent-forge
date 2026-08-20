# Security Model — agent-forge

Русская версия ниже. This document states the exact trust boundaries of agent-forge so the marketing claims stay honest.

## What is enforced in code

- **`write_file` scope.** The coder/repair agents can write only inside the task's `scope_paths` (gitignore-like masks). `canon/` is always read-only. Violations are blocked and logged to `runs/<run_id>/events.jsonl`. Path escape outside the target root (`../`) is blocked.
- **Dependency installs are blocked** at tool level (`npm install`, `pip install`, `dotnet add`, `npx` — regex denylist). A new dependency is the owner's decision; the agent must finish with `BLOCKED` and a rationale.
- **Command allowlist.** `run_command` accepts only commands whose segments start with an allowlisted binary (default: `python`, `pytest`, `npm`, `node`, `dotnet`, `ruff`, `mypy`).
- **No git push, ever.** agent-forge creates branches and local commits; only the owner pushes.
- **Secrets.** API keys live only in `.env` (gitignored); journal events never contain key material.

## What is NOT a sandbox

- **`run_command` is a guardrail, not a security boundary.** Allowlisted binaries are Turing-complete: `python -c ...` or a malicious `npm test` script can execute arbitrary code with the owner's OS user rights, including writing *outside* `scope_paths`. The scope control protects against model mistakes and scope drift, not against a deliberately adversarial model output.
- **`acceptance` commands in `tasks.yaml` are trusted owner code.** They run via the shell (`shell=True`) with full user rights. Treat `tasks.yaml` like a Makefile: never run a queue you haven't read.
- **Agent-written code runs on the host.** When acceptance commands execute code the agent just wrote (that is the point of the tool), that code has your user's privileges. If you need hard isolation, run the whole `forge run` inside a container or VM yourself — first-class sandboxed execution is on the roadmap.

## Practical recommendations

1. Run against a dedicated clone/worktree of the target repo, not your only working copy.
2. Review `tasks.yaml` (especially `acceptance`) before every run.
3. Use per-task / per-run / per-day USD budget caps — they bound financial damage even if everything else goes wrong.
4. Keep `FORGE_MOCK=1` for CI; real runs on machines where a stray `python -c` is acceptable.
5. Prefer providers/endpoints you trust with your code; prompts contain spec excerpts and file contents.

## Reporting

Security issues: open a private GitHub Security Advisory on the repository, not a public issue.

---

## Модель безопасности (кратко по-русски)

**Гарантируется кодом:** запись только в `scope_paths` задачи; `canon/` — всегда read-only; установка зависимостей заблокирована; запуск команд — только из allowlist; никакого `git push`; секреты — только в `.env` и не попадают в журнал.

**Не является песочницей:** allowlist-команды (`python`, `npm`…) могут исполнить произвольный код — scope-контроль защищает от ошибок и дрейфа модели, а не от намеренно вредоносного вывода. `acceptance`-команды — доверенный код владельца на shell. Агентский код исполняется на хосте с правами вашего пользователя; для жёсткой изоляции запускайте `forge run` в контейнере/ВМ (встроенный сандбокс — в роадмапе).

**Рекомендации:** отдельный клон целевого репо; читайте `tasks.yaml` перед запуском; всегда ставьте бюджетные капы; `FORGE_MOCK=1` в CI.
