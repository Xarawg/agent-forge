"""Оркестратор прогона: DAG задач, фазы, гейты, бюджеты, git (SPEC.md §FR-2..FR-7)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .agents import parse_verdict, run_reviewer, run_tool_agent
from .config import ForgeConfig
from .journal import Journal, new_run_id
from .llm import LLMClient
from .models import Task, TaskPackage, TaskState, load_tasks, topo_order
from .prompts import load_prompt, prompts_version, render
from .tools import _WINDOWS_ENV_DEFAULTS, ToolBox

ACCEPTANCE_TIMEOUT = 300
EXCERPT_LIMIT = 30000  # калибровка пилотом: 8000 обрезало validate_canon.py (10.7K) в середине


def run_shell(root: Path, command: str, timeout: int = ACCEPTANCE_TIMEOUT) -> tuple[int, str]:
    """Прогон доверенной команды владельца (acceptance из tasks.yaml)."""
    env = dict(os.environ)
    if os.name == "nt":
        for var, default in _WINDOWS_ENV_DEFAULTS.items():
            env.setdefault(var, default)
    try:
        proc = subprocess.run(
            command, shell=True, cwd=root, capture_output=True, text=True, timeout=timeout,
            env=env,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT после {timeout}s"


class Runner:
    def __init__(self, cfg: ForgeConfig, client: LLMClient, target_root: Path) -> None:
        self.cfg = cfg
        self.client = client
        self.target = target_root.resolve()
        self.system_prompt = load_prompt(cfg.prompts_dir, "system")

    # --- публичный вход -------------------------------------------------------

    def run(self, tasks_path: Path, run_id: str | None = None, spec_path: Path | None = None) -> str:
        package = load_tasks(tasks_path)
        run_id = run_id or new_run_id()
        journal = Journal(self.cfg.runs_dir, run_id)
        if not journal.meta_path.exists():
            journal.write_meta(
                {
                    "run_id": run_id,
                    "package": package.name,
                    "tasks_path": str(tasks_path),
                    "target_root": str(self.target),
                    "spec_path": str(spec_path) if spec_path else None,
                    "provider": self.cfg.provider_name,
                    "mock": self.cfg.mock,
                    "models": {role: rc.model for role, rc in self.cfg.roles.items()},
                    "prompts_version": prompts_version(self.cfg.prompts_dir),
                    "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "accepted": [],
                }
            )
        journal.event(phase="run", note=f"run {run_id} started (package {package.name})")

        ordered = topo_order(package.tasks)
        for task in ordered:
            state = journal.task_state(task.id)
            if state.state == "done":
                continue
            gate_holder = self._pending_gate(journal, ordered, task)
            if gate_holder:
                journal.event(
                    task_id=task.id, phase="gate",
                    note=f"run paused: ждёт `forge accept {gate_holder}` (человеческий гейт №3)",
                )
                break
            self._run_task(journal, package, task, spec_path)
            if self._run_cost(journal) >= self.cfg.budgets.per_run_max_cost_usd:
                journal.event(phase="budget", note="per-run кап стоимости достигнут, прогон остановлен")
                break
        journal.event(phase="run", note=f"run {run_id} finished")
        return run_id

    # --- одна задача -----------------------------------------------------------

    def _run_task(
        self, journal: Journal, package: TaskPackage, task: Task, spec_path: Path | None
    ) -> None:
        state = journal.task_state(task.id)

        if not self._check_budgets(journal, task, state):
            return

        branch = self._git_branch(task)
        note = f"branch: {branch}" if branch else "branch: (не git-репозиторий, пропуск)"
        journal.event(task_id=task.id, phase="git", note=note)

        state.state = "running"
        journal.set_task_state(state)
        toolbox = ToolBox(self.target, task.scope_paths, self.cfg.command_allowlist)
        user_prompt = self._task_prompt(package, task, spec_path, history="(первая итерация)")
        outcome = run_tool_agent(
            self.client, self.cfg, journal,
            role="coder",
            system_prompt=self.system_prompt + "\n\n" + load_prompt(self.cfg.prompts_dir, "coder"),
            user_prompt=user_prompt,
            toolbox=toolbox,
            task_id=task.id,
            phase="coder",
            history_path=self._history_path(journal, task, "coder"),
        )
        self._sync_usage(journal, state)

        if outcome.marker in ("BLOCKED", "GAP"):
            state.state = "blocked"
            journal.set_task_state(state, note=f"{outcome.marker}: {outcome.text[-500:]}")
            return
        if outcome.marker == "STEPS_EXHAUSTED":
            state.state = "failed"
            journal.set_task_state(state, note="исчерпаны шаги агента без маркера DONE")
            return

        # Гейт №2: валидация + reviewer, затем repair-цикл (SPEC.md §FR-3).
        history: list[str] = []
        max_repairs = self.cfg.budgets.repair_max_iterations
        for attempt in range(max_repairs + 1):
            ok, validation_log = self._validate(journal, task)
            verdict, verdict_text = self._review(journal, task, toolbox, ok, validation_log)
            if ok and verdict == "APPROVE":
                self._git_commit(task, toolbox)
                state = journal.task_state(task.id)
                state.state = "done"
                state.repair_iterations = attempt
                journal.set_task_state(state, note="acceptance зелёный, reviewer APPROVE")
                return
            if verdict == "REJECT":
                state = journal.task_state(task.id)
                state.state = "failed"
                state.repair_iterations = attempt
                journal.set_task_state(state, note=f"reviewer REJECT: {verdict_text[-500:]}")
                return
            if attempt >= max_repairs:
                break
            # repair-итерация (состояния по SPEC.md §FR-4: repair = повторный running)
            state = journal.task_state(task.id)
            state.state = "running"
            journal.set_task_state(state, note=f"repair iteration {attempt + 1}/{max_repairs}")
            history.append(
                f"## Repair iteration-{attempt + 1}\n"
                f"Вердикт reviewer: {verdict_text}\nВывод валидации:\n{validation_log[-2000:]}"
            )
            repair_prompt = self._task_prompt(package, task, spec_path, history="\n\n".join(history))
            outcome = run_tool_agent(
                self.client, self.cfg, journal,
                role="repair",
                system_prompt=self.system_prompt + "\n\n" + load_prompt(self.cfg.prompts_dir, "repair"),
                user_prompt=repair_prompt,
                toolbox=toolbox,
                task_id=task.id,
                phase="repair",
                history_path=self._history_path(journal, task, "repair"),
            )
            self._sync_usage(journal, journal.task_state(task.id))
            if outcome.marker in ("STUCK", "DISPUTE"):
                state = journal.task_state(task.id)
                state.state = "failed" if outcome.marker == "STUCK" else "blocked"
                state.repair_iterations = attempt + 1
                journal.set_task_state(state, note=f"{outcome.marker}: {outcome.text[-500:]}")
                return
            if not self._check_budgets(journal, task, journal.task_state(task.id)):
                return

        state = journal.task_state(task.id)
        state.state = "failed"
        state.repair_iterations = max_repairs
        journal.set_task_state(
            state,
            note=f"не починено за {max_repairs} repair-итераций; см. events.jsonl",
        )

    # --- фазы ------------------------------------------------------------------

    @staticmethod
    def _history_path(journal: Journal, task: Task, phase: str) -> Path:
        """Снапшот диалога фазы (AF-08): переживает kill прогона, читается resume."""
        return journal.run_dir / "tasks" / f"{task.id}.{phase}.history.json"

    def _validate(self, journal: Journal, task: Task) -> tuple[bool, str]:
        state = journal.task_state(task.id)
        state.state = "validating"
        journal.set_task_state(state)
        logs: list[str] = []
        ok = True
        for command in task.acceptance:
            code, output = run_shell(self.target, command)
            journal.event(task_id=task.id, phase="validate", command=command, exit_code=code,
                          note=output[:1500])
            logs.append(f"$ {command}\nexit_code={code}\n{output}")
            if code != 0:
                ok = False
        return ok, "\n\n".join(logs)

    def _review(
        self, journal: Journal, task: Task, toolbox: ToolBox, acceptance_ok: bool, validation_log: str
    ) -> tuple[str, str]:
        state = journal.task_state(task.id)
        state.state = "review"
        journal.set_task_state(state)
        written = self._written_snapshot(toolbox)
        prompt = (
            f"Задача {task.id}: {task.title}\nСпека: {task.spec_ref}\n\n"
            f"ACCEPTANCE_STATUS: {'OK' if acceptance_ok else 'FAIL'}\n\n"
            f"## Вывод acceptance-команд\n{validation_log[-4000:]}\n\n"
            f"## Записанные файлы (diff-замена)\n{written}"
        )
        text = run_reviewer(
            self.client, self.cfg, journal,
            system_prompt=self.system_prompt + "\n\n" + load_prompt(self.cfg.prompts_dir, "reviewer"),
            review_prompt=prompt,
            task_id=task.id,
        )
        return parse_verdict(text), text

    def _written_snapshot(self, toolbox: ToolBox) -> str:
        """Содержимое записанных файлов как замена diff (v1, см. docs/DECISIONS.md / docs/DECISIONS.ru.md)."""
        chunks: list[str] = []
        for rel in toolbox.written_files:
            try:
                text = (self.target / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                text = "<binary/unreadable>"
            chunks.append(f"### {rel}\n```\n{text[:3000]}\n```")
        return "\n\n".join(chunks) or "(файлы не записаны)"

    # --- бюджеты -----------------------------------------------------------------

    def _check_budgets(self, journal: Journal, task: Task, state: TaskState) -> bool:
        task_budget = task.budget
        max_tokens = task_budget.max_tokens or self.cfg.budgets.per_task_max_tokens
        if state.tokens_in + state.tokens_out >= max_tokens:
            state.state = "blocked"
            journal.set_task_state(state, note=f"per-task кап токенов ({max_tokens}) исчерпан")
            return False
        max_cost = task_budget.max_cost_usd
        if max_cost is not None and state.cost_usd >= max_cost:
            state.state = "blocked"
            journal.set_task_state(state, note=f"per-task кап стоимости (${max_cost}) исчерпан")
            return False
        if self._run_cost(journal) >= self.cfg.budgets.per_run_max_cost_usd:
            state.state = "blocked"
            journal.set_task_state(
                state, note=f"per-run кап стоимости (${self.cfg.budgets.per_run_max_cost_usd}) исчерпан"
            )
            return False
        if self._day_cost() >= self.cfg.budgets.per_day_max_cost_usd:
            state.state = "blocked"
            journal.set_task_state(
                state, note=f"per-day кап стоимости (${self.cfg.budgets.per_day_max_cost_usd}) исчерпан"
            )
            return False
        return True

    def _sync_usage(self, journal: Journal, state: TaskState) -> None:
        """Пересчитать токены/стоимость задачи из журнала."""
        events = journal.log_for_task(state.id)
        state.tokens_in = sum(e.get("tokens_in", 0) for e in events)
        state.tokens_out = sum(e.get("tokens_out", 0) for e in events)
        state.cost_usd = round(sum(e.get("cost_usd", 0.0) for e in events), 6)
        journal.set_task_state(state)

    @staticmethod
    def _run_cost(journal: Journal) -> float:
        return float(sum(e.get("cost_usd", 0.0) for e in journal.read_events()))

    def _day_cost(self) -> float:
        today = datetime.now(UTC).date().isoformat()
        total = 0.0
        for events_path in self.cfg.runs_dir.glob("*/events.jsonl"):
            for line in events_path.read_text(encoding="utf-8").splitlines():
                if f'"ts": "{today}' in line:
                    total += json.loads(line).get("cost_usd", 0.0)
        return total

    # --- гейты и git ------------------------------------------------------------

    @staticmethod
    def _pending_gate(journal: Journal, ordered: list[Task], current: Task) -> str | None:
        """id ранее завершённой задачи с gate-меткой, ожидающей `forge accept`."""
        accepted = set(journal.accepted_tasks())
        for task in ordered:
            if task.id == current.id:
                return None
            if task.gate and task.id not in accepted:
                if journal.task_state(task.id).state == "done":
                    return task.id
        return None

    def _git(self, *args: str) -> tuple[int, str]:
        return run_shell(self.target, "git " + " ".join(args), timeout=60)

    def _is_git_repo(self) -> bool:
        code, _ = self._git("rev-parse", "--is-inside-work-tree")
        return code == 0

    def _git_branch(self, task: Task) -> str | None:
        """Ветка на задачу (SPEC.md §1.4, NFR-5: push — только владельцем)."""
        if not self._is_git_repo():
            return None
        branch = f"forge/{task.id}"
        code, out = self._git("checkout", "-B", branch)
        return branch if code == 0 else None

    def _git_commit(self, task: Task, toolbox: ToolBox) -> None:
        """Локальный коммит после гейта reviewer (prompts/20). Push запрещён."""
        if not self._is_git_repo() or not toolbox.written_files:
            return
        for rel in toolbox.written_files:
            self._git("add", "--", f'"{rel}"')
        self._git("commit", "-m", f'"forge: {task.id} — {task.title}"')

    def accept(self, run_id: str, task_id: str) -> None:
        """Человеческий гейт №3: фиксация приёмки + локальный merge ветки задачи."""
        journal = Journal(self.cfg.runs_dir, run_id)
        journal.accept_task(task_id)
        if self._is_git_repo():
            code, out = self._git("merge", "--no-ff", f"forge/{task_id}")
            journal.event(task_id=task_id, phase="gate", command=f"git merge forge/{task_id}",
                          exit_code=code, note=out[:1000])

    # --- промпт задачи ------------------------------------------------------------

    def _task_prompt(
        self, package: TaskPackage, task: Task, spec_path: Path | None, history: str
    ) -> str:
        spec_excerpt = "(не приложена)"
        if spec_path and spec_path.exists():
            spec_excerpt = spec_path.read_text(encoding="utf-8")[:EXCERPT_LIMIT]
        canon_excerpt = "(нет)"
        if package.canon_snapshot:
            canon_path = self.target / package.canon_snapshot
            if canon_path.exists():
                canon_excerpt = canon_path.read_text(encoding="utf-8")[:EXCERPT_LIMIT]
        template = load_prompt(self.cfg.prompts_dir, "task_template")
        return render(
            template,
            {
                "task.id": task.id,
                "task.title": task.title,
                "task.spec_ref": task.spec_ref,
                "package.name": package.name,
                "spec_excerpt": spec_excerpt,
                "canon_excerpt": canon_excerpt,
                "task.scope_paths": "\n".join(f"- `{p}`" for p in task.scope_paths),
                "task.acceptance": "\n".join(f"- `{c}`" for c in task.acceptance),
                "history": history,
            },
        )
