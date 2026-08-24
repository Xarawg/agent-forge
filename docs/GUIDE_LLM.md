# How LLMs write code: theory, tools, and where agent-forge fits

> Living document. Updated as agent-forge and its competitors evolve.
> Last revision: 2026-08. If you read this months later, re-check the
> "Alternatives" section and send a PR with corrections.
> Русская версия: [GUIDE_LLM.ru.md](GUIDE_LLM.ru.md).

A document for newcomers deciding **how** to structure LLM-assisted work on
their project — and whether agent-forge is the right fit. No marketing: where
our solution is strong, where it is weak, and when another tool is honestly
the better choice.

## 1. Foundations: how an LLM assistant differs from a compiler

An LLM does not "know" your project. Everything the model accounts for lives
in the **context window**: the text you fed it in this specific request. All
engineering problems of LLM code generation follow from this fact:

1. **Context is money and quality at once.** Every token in the window costs
   money; on long contexts model attention degrades — an instruction like
   "do not duplicate X" works noticeably worse at token 90K than at token 5K.
   The central task of any tool is therefore **context selection**: give the
   model exactly the files, contracts, and decisions the task needs.
2. **The model cannot verify itself.** It generates plausible code, not
   correct code. The only reliable validator is external: compiler, tests,
   linters. Mature tools are built around **acceptance commands**, not around
   a "clever prompt".
3. **Without explicit bounds an agent sprawls.** Ask a model to "improve the
   service" without boundaries and you get edits in eight files, a refactor to
   the model's taste, and a duplicate of an existing data model. Hence
   **scope control** and a **catalog of existing entities** as mandatory
   mechanisms.
4. **Reproducibility does not happen by itself.** If the outcome depends on
   which files the model decided to read today, the run cannot be repeated.
   You need journaling and deterministic pipeline stages.

## 2. The 2026 solution spectrum

Tools differ primarily in **who selects context and how**, and **where the
human checkpoints are**.

### 2.1. Browser chat (ChatGPT, Claude, DeepSeek-web)

The human copies context by hand. Full control, zero automation. Fine for
one-off questions; wrong for project development — the human becomes the
bottleneck and the source of context-selection errors.

### 2.2. IDE copilots (GitHub Copilot, Cursor, Windsurf)

The IDE selects context: autocomplete + chat over a codebase index
(embeddings/RAG + heuristics). Strong at "I type, it suggests", weaker at
multi-step tasks; the RAG index is non-deterministic — semantic similarity is
not contract-level relatedness. The gate between "suggested" and "committed"
is you, in real time. A good choice for interactive pairing; a poor one for
auditable, reproducible runs.

### 2.3. Agentic CLIs (Claude Code, Aider, goose, OpenHands, Codex CLI)

The model works in a "model ↔ tools" loop inside your repository: reads
files, edits, runs tests. Context strategies:
- **Aider** — tree-sitter repo-map: compact signatures of the whole repo,
  full file contents only for edit targets. Deterministic and cheap;
- **Claude Code** — import-following + search, hierarchical
  CLAUDE.md/AGENTS.md as a conventions layer;
- **OpenHands / swe-agent** — autonomous agents for benchmark-style tasks,
  minimal control.

The liveliest class of tools. Common weakness: budget control, gates, and
audit are optional rather than built in; run state usually lives in a
session, not in an on-disk journal.

### 2.4. Spec-driven methodologies (GitHub spec-kit, BMAD method)

A "specification → plan → tasks → code" pipeline layered on top of agentic
CLIs. Strong idea: the spec is the source of truth, code is derived.
Weakness: these are prompt/procedure libraries over someone else's runner;
execution, budgets, and validation remain the underlying tool's problem.

### 2.5. Gated run orchestrators (agent-forge is here)

The focus is not a "smart agent" but a **governed pipeline**: the task queue
as a contract (tasks.yaml); every task carries scope, owner-written
acceptance commands, a budget, and a gate; state lives on disk; every model
call is journaled; a run can be killed and resumed. The model is a
replaceable part (any OpenAI-compatible endpoint); the intelligence is in the
process structure.

## 3. Key tradeoffs (what each approach sacrifices)

| Axis | Copilots (2.2) | Agentic CLIs (2.3) | Spec methodologies (2.4) | agent-forge (2.5) |
|---|---|---|---|---|
| Time to start | instant | minutes | hours of methodology | minutes (wizard) |
| Interactivity | full | high | medium | low (gates) |
| Budget control | none | weak | none | per-task/run/day caps |
| Result validation | by eye | tests at model's discretion | per procedure | frozen owner acceptance commands |
| Audit/reproducibility | none | session | runner-dependent | full events.jsonl journal |
| Context selection | RAG (non-det.) | repo-map/search | manual via spec | entity map + import graph |
| Entry barrier | zero | low | high | medium |

## 4. How agent-forge selects context (our answer to §1)

Deterministically, without embeddings (the comparison motivating this choice:
RAG non-determinism breaks run reproducibility):

1. **`forge map`** — AST scan of the project → `canon/entities.json`: all
   public entities (models, contracts, services) with signatures and the
   import graph.
2. The coder prompt for a task carries three layers:
   - its **scope** files — read and edited by the agent itself (write_file is
     scope-restricted);
   - a **name catalog of every entity** in the project — anti-duplication:
     "`UserModel` already exists in `models/user.py`; import it, do not
     rewrite";
   - **signatures of neighbors** in the import graph (depth 1) — related
     contracts visible without reading their files in full.
3. The target repo's `AGENTS.md` — a conventions layer in the same prompt.
4. Spec and canon — excerpts under a hard limit (30K characters).

## 5. When agent-forge is the right choice — and when it is not

**Take agent-forge if:** you need an auditable run with budgets and gates;
work proceeds in task packages derived from a specification; the project is
large/legacy and scope control matters; you want replaceable cheap models
instead of a premium subscription.

**Honestly take something else if:** you want interactive pairing in the
editor (Copilot/Cursor); the task is one-off and small (chat); you are
exploring autonomous-agent limits (OpenHands); you have no checks at all and
are not ready to write any — acceptance-orientation will then feel like
friction.

## 6. Maintaining this document

Revisit when: agent-forge gains new context mechanisms (repo-map →
tree-sitter for TS/Go etc.), significant versions of §2 tools ship, or new
solution classes appear. Editing rules: verifiable facts, comparisons along
the §3 axes, no promotional phrasing.
