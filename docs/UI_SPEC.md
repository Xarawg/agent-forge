# agent-forge Web UI Specification

Source of truth is the code: `forge/ui.py` (server, API, wizard form
rendering), `forge/ui_static/index.html` (kanban, report, event panel), plus
`forge/cli.py` + `forge/report.py` (the `status` / `log` / `report` commands
that expose the same data in the terminal).

The UI is the `forge ui` command: a local web server on pure stdlib
(`http.server.ThreadingHTTPServer`) bound to `127.0.0.1` (default port 8765)
that renders the contents of the `runs/` directory. Almost everything is
read-only; the single mutation is rewriting the queue draft YAML in `/wizard`
(see §2).

---

## 1. Personas and scenarios

### 1.1. Owner monitoring a run

Context: a run was started from the terminal (`forge run` / `forge resume`);
the owner wants to watch progress without reading raw JSON.

1. Runs `forge ui` (no API key needed), opens `http://127.0.0.1:8765/`.
2. Selects a run from the dropdown in the header (defaults to the last one by
   directory name `run-YYYYmmdd-HHMMSS`). Sees provider, mock flag, start
   time, and total cost.
3. Watches the kanban: 7 columns matching the runner's real states
   (`queued → running → validating → review → blocked → failed → done`).
   Task card: title, id, gate badge `⛳ <gate>`, cost, tokens `in+out`,
   repair-iteration count, note (truncated to 500 chars).
4. The page auto-refreshes every 3 seconds (fetch with `no-store`, no page
   reload). An open event panel refreshes too.
5. Clicking a card opens a slide-in panel on the right with the task's event
   journal (equivalent of `forge log <task_id>`): timestamp, phase, role,
   command, exit code, tokens/cost, note.
6. The "Отчёт" (Report) button shows a table of all tasks in the run with a
   totals row (equivalent of `forge report` without `--plain`).
7. If the run is parked at a gate, the owner sees the task in the `done`
   column with a `⛳` badge, but **the "⏸ forge accept … && forge resume …"
   hint is not shown in the UI** — it exists only in `forge status` (see §3).

### 1.2. Owner editing the queue draft

Context: `forge wizard` / `forge import` produced a `tasks.wizard.yaml`
draft; before launch (gate #1) it must be reviewed and edited.

1. Opens `http://127.0.0.1:8765/wizard?file=<path to tasks.wizard.yaml>`.
2. Sees one card per task: title, spec_ref, scope_paths, acceptance, caps
   (max_tokens / max_cost_usd), gate. Plus lint warnings (`forge lint`
   advisor) and a cost forecast "no more than ~$X (sum of caps)".
3. Edits fields, clicks "Сохранить черновик" (Save draft). The server
   validates the tasks.yaml contract (DAG, kebab-id, scope) **before**
   writing; on error the file is left unchanged, on success the replacement
   is atomic (temp file + `os.replace`). `depends_on` is not editable in the
   form and is preserved from the original file.
4. Starts the run from the terminal — the form itself prints the command
   `forge run --tasks <file> --target .`.

### 1.3. Newcomer looking at "what is even happening"

Context: a person opens the UI without any background in tokens and states.

1. If there are no runs — an empty state with a hint: "Прогонов пока нет —
   запустите `forge run`" (No runs yet — run `forge run`).
2. Columns are labeled in Russian ("Очередь", "В работе", "Валидация",
   "Ревью", "Заблокировано", "Провалено", "Готово") with color-coded states.
3. The plain-language report (`forge report --plain`: "Done N of M", ✅/❌/⏸,
   "what next") exists **only in the CLI** — there is no UI equivalent
   (see §3).

---

## 2. Capability catalog

### 2.1. Screens and API endpoints

| Screen / endpoint | Data | Actions | Constraints |
|---|---|---|---|
| `GET /` (`/index.html`) — kanban | Static `forge/ui_static/index.html` (inline CSS/JS, no external resources). Data is fetched by JS via the API. | Run selection, "Канбан"/"Отчёт" view toggle, event panel. Auto-refresh every 3 s. | Read-only. All rendering is client-side. |
| `GET /api/runs` | List of runs from `runs/`: `run_id`, `started_at`, `package`, `provider`, `mock`, state counters `states{}`, `total_cost_usd` (sum of `cost_usd` over events.jsonl). | Run selection in the dropdown. | Broken/missing `run.json` → empty fields, server does not crash. Directories without `run.json` are still listed. |
| `GET /api/run/<run_id>` | Run meta (full `run.json`), task array: `id`, `title` and `gate` (from tasks.yaml via `meta.tasks_path`), `state`, `cost_usd`, `tokens_in/out`, `repairs`, `note` (≤500 chars). `totals` (sums). | Kanban and report rendering. | 404 for nonexistent/invalid `run_id`. Only tasks **with journal entries** (`tasks/<id>.json`); queued tasks from the queue without entries are not included (unlike CLI status). `*.history.json` snapshots (AF-12) are excluded. |
| `GET /api/run/<run_id>/events?task=<id>&tail=<n>` | Last `tail` events of `events.jsonl` (default 50, max 500), optionally filtered by `task_id`. Event fields: `ts`, `phase`, `role`, `model`, `command`, `exit_code`, `tokens_in/out`, `cost_usd`, `note` (≤500 chars + "…"). | Task event panel (equivalent of `forge log`). | 404 for invalid `run_id`. Broken JSONL lines are skipped. Filter is single-task only; the UI never requests "all run events". |
| `GET /wizard?file=<path.yaml>` | Draft HTML form: task cards (title, spec_ref, scope_paths, acceptance, max_tokens, max_cost_usd, gate), lint warnings, cost forecast (sum of caps), launch command hint. | View/edit draft fields. | `file` must be an existing `*.yaml`/`*.yml`, otherwise 400. Cannot add/remove tasks, change `depends_on` or ordering. |
| `POST /wizard/save` | Draft rewrite from the form. | Save with contract validation before write; atomic replace; response is the same form with an "ok"/"err" message. | **The only UI mutation.** `runs/` is untouched. `depends_on` is preserved from the original file. On contract failure the file is not changed. |
| Other paths | JSON `{"error": "not found"}` | — | 404. |

### 2.2. Client-side logic (index.html)

- **Kanban columns** — fixed `STATE_ORDER`; states outside the list (legacy
  runs) are appended as extra columns at the end.
- **Run selector**: defaults to the last entry of `/api/runs`; the selection
  is preserved across refreshes while the run still exists.
- **Event panel**: fixed on the right (46% width, min 420 px), auto-scrolls
  to the bottom, closed via "✕" or run switch; refreshes together with run
  details.
- **Escaping**: all user content goes through `esc()` (client-side XSS
  protection) and `html.escape` (server-side wizard).
- **Header line**: `provider · mock · started_at`, total `$X.XXXX`.

### 2.3. Parity with the CLI (status / log / report)

| Data | CLI | UI |
|---|---|---|
| Run task table | `forge status` — the **full queue** from tasks.yaml (topological order); tasks without journal entries shown as `queued` → honest "N of M" | Kanban/report — only tasks with journal entries |
| Gate-wait hint | `forge status`: "⏸ Прогон ждёт решения: `forge accept <id> && forge resume <run>`" (`report._gate_wait`) | None |
| Gate badge on a task | Not in the status table | Present: `⛳ <gate>` on the card |
| Task journal | `forge log <task_id>` (note up to 400 chars) | Event panel (note up to 500 chars) |
| Summary | `forge report`: + per-run cap with OK/ПРЕВЫШЕНИЕ verdict, per-role models, prompts version | "Отчёт" tab: table + totals only |
| Plain-language report | `forge report --plain` ("Done N of M", ✅/❌/⏸, next commands) | None |

---

## 3. UX gaps (statement of fact, no design)

What the CLI can do that the UI cannot:

1. **Gate #3 from the browser**: `forge accept <task_id>` and
   `forge resume <run_id>` are terminal-only. The UI does not even show the
   "⏸ run is waiting for a decision…" hint — an owner watching only the
   browser will not learn that the run is parked at a gate (the task looks
   like an ordinary `done` with a `⛳` badge).
2. **Starting a run**: `forge run` / `forge resume` are unavailable from the
   UI; there is no "launch queue" button even in the wizard form (only a
   textual command hint).
3. **Viewing the task branch diff**: neither changed files nor the task
   branch's `git diff` are shown; only the note and events.
4. **Cost over time**: no cost/token chart or timeline — only aggregates
   (per task and total).
5. **Honest "N of M"**: the UI does not show queued tasks without journal
   entries, so the full queue and "N of M" progress are visible only in
   `forge status` / `forge report --plain`.
6. **Plain-language report** (`report --plain`): the "Succeeded / Failed /
   Waiting / What next" sections are CLI-only.
7. **Per-run cap and reproducibility**: cap verdict, per-role models, prompts
   version (`forge report`) are absent from the UI report.
8. **Dry-run forecast** (`forge run --dry-run`) is not in the UI; the wizard
   shows only the sum of caps.
9. **Whole-run events**: the API can return events without a task filter, but
   the UI never uses that view; there is no log search.
10. **Wizard form**: cannot add/remove a task, change `depends_on` or task
    order — only editing fields of existing tasks.
11. **Notifications**: no sound/badge on state change or gate stop; only
    passive auto-refresh.
12. **Interface language**: Russian only (no English UI).
13. **Run list**: only a dropdown; no runs table with comparison (cost,
    states), although `/api/runs` returns that data.
14. **Mobile layout**: the 420 px-min event panel and 220 px-min columns
    require horizontal scrolling on narrow screens.

---

## 4. Non-functional requirements

1. **Read-only on `runs/`**: the server never creates, modifies, or deletes
   anything in `runs/`. The single mutation is rewriting one draft YAML file
   via `/wizard/save` (atomic: sibling temp file + contract validation +
   `os.replace`; on error the original file is untouched).
2. **No keys**: the UI never calls an LLM and requires no API key; the
   provider config is not loaded. Secrets never enter events.jsonl per the
   journal contract (`journal.event`).
3. **Localhost**: binds to `127.0.0.1` only; default port 8765, `--port 0`
   is ephemeral (tests). No authentication — it is assumed to be the owner's
   local tool.
4. **Offline statics**: a single `index.html` with inline CSS/JS; zero
   external CDNs, fonts, or analytics. The server is pure stdlib
   (`http.server`, `json`, `urllib`, `html`, `tempfile`); the only external
   dependency is PyYAML (already in the project). Statics are read from
   `forge/ui_static/` next to the module — works in editable installs too.
5. **Data resilience**: broken/missing `run.json`, `tasks/*.json`, or
   `events.jsonl` lines never crash the server (empty structures / skipped
   lines). `BrokenPipeError`/`ConnectionResetError` on response are ignored.
   Path traversal protection: a `run_id` containing `/`, `\`, `..` is
   rejected (404).
6. **Caching**: all responses carry `Cache-Control: no-store`; client fetches
   use `no-store` too — the UI always shows the current state of runs/.
7. **Languages**: the interface is Russian; documentation (this file and
   `UI_SPEC.ru.md`) is Russian + English.
8. **Data truncation**: `note` — 500 chars in the API (cards and events);
   event `tail` — 1 to 500; command in the log viewer — up to 200 chars per
   line.
