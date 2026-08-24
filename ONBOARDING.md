# Onboarding: join the agent-forge project in 30 minutes

> Русская версия: [ONBOARDING.ru.md](ONBOARDING.ru.md).
> This is the only file a newcomer needs to read end to end.
> Everything else is linked from here.

## What this project is

agent-forge is a local orchestrator of LLM code generation: you describe work
as a task queue (manually, from a spec, or in plain words via the wizard),
agents write code per task, every task is validated by **your** commands
(tests, linters), and human gates stand between stages. Any OpenAI-compatible
model; spending is capped; everything is journaled. Full theory and a
comparison with alternatives — [docs/GUIDE_LLM.md](docs/GUIDE_LLM.md).

## Install (5 minutes)

Requirements: Windows 10/11 + Git Bash (or Linux/macOS), Python 3.12+, git.

```bash
git clone https://github.com/Xarawg/agent-forge.git
cd agent-forge
python -m venv .venv && source .venv/Scripts/activate   # Linux/macOS: .venv/bin/activate
pip install -e ".[dev]"
```

Verify without any API key or spend (mock mode):

```bash
FORGE_MOCK=1 forge run --tasks config/tasks.example.yaml --target /tmp/any-folder --dry-run
pytest -q    # 105+ tests, all green
```

## First run on your own project (15 minutes)

```bash
# 1. Provider key (any OpenAI-compatible; presets in config/providers/)
cp .env.example .env   # set FORGE_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY

# 2. Prepare your project (git, baseline checks, cap profile)
forge init --target /path/to/project --profile careful

# 3. Large project? Entity map first — deterministic, $0:
forge map --target /path/to/project
# → docs/ENTITIES.md (for you) + canon/entities.json (for agents: anti-dup, import neighbors)

# 4. Draft tasks in plain words (one LLM call) or a deterministic recipe:
forge wizard --target /path/to/project --prompt "what needs to be done"
forge wizard --target /path/to/project --recipe test-coverage   # no LLM, $0

# 5. Gate #1: open tasks.wizard.yaml, review/edit the tasks
forge lint /path/to/project/tasks.wizard.yaml

# 6. Run
forge run --tasks /path/to/project/tasks.wizard.yaml --target /path/to/project
```

## How to watch a run

```bash
forge status                 # task table; if the run waits for you — a ⏸ line with the command
forge log <task-id>          # full event journal of one task (model calls, commands)
forge report --plain         # plain-language outcome: done N of M, spent $X
forge ui                     # kanban at http://127.0.0.1:8765 (read-only)
```

The `careful` profile pauses after every task: review the diff, then
`forge accept <task-id>` and `forge resume <run_id>`. A DISPUTE/failed state
is not a disaster but a decision point: inspect via `forge log`, override
manually with the same `forge accept` when appropriate.

## Repository map

| Path | Contents |
|---|---|
| `forge/` | tool code (runner, agents, wizard, map, report…) |
| `prompts/` | role prompt library (00 system … 60 AGENTS) |
| `config/` | models.yaml (roles/prices/caps), providers/*.yaml, recipes/*.yaml |
| `docs/` | SPEC (normative), GUIDE_LLM (theory), USECASES (scenarios), DECISIONS (AF-* log) |
| `canon/entities.json` | entity map of this repo (`forge map` output) |
| `tests/` | pytest; mock mode, no API key needed |
| `runs/` | run journals (local, not committed) |

## How to contribute (process)

1. Contested decisions — first a `docs/DECISIONS.md` entry (AF-N format).
2. Code comes with tests; before committing: `pytest -q`,
   `ruff check forge tests`, `mypy forge`. CI runs the same.
3. Changed agent behavior — update the prompt library, SPEC, and USECASES
   too (they describe observed behavior, not intended).
4. Changed the public surface of `forge/` — regenerate the map:
   `forge map --target .` (commit the artifacts: `canon/entities.json`,
   `docs/ENTITIES.md`).

## What to read next

- New to LLM-assisted development: [docs/GUIDE_LLM.md](docs/GUIDE_LLM.md)
- Real scenarios with under-the-hood walkthroughs: [docs/USECASES.md](docs/USECASES.md)
- Configuration and the tasks.yaml contract: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
