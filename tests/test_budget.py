"""Бюджетные капы (SPEC.md §FR-5): per-task, per-run, per-day → blocked."""

import json
from datetime import UTC, datetime
from pathlib import Path

from conftest import TASK_OK, write_tasks

from forge.journal import Journal
from forge.runner import Runner


def test_per_task_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None:
    tasks = write_tasks(tmp_path, TASK_OK.replace(
        "acceptance:",
        "budget: {max_cost_usd: 0.0}\n    acceptance:",
    ))
    run_id = runner.run(tasks)
    state = Journal(cfg.runs_dir, run_id).task_state("task-ok")
    assert state.state == "blocked"
    assert "per-task" in state.note and "стоимости" in state.note


def test_per_run_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None:
    cfg.budgets.per_run_max_cost_usd = 0.0
    run_id = runner.run(write_tasks(tmp_path, TASK_OK))
    state = Journal(cfg.runs_dir, run_id).task_state("task-ok")
    assert state.state == "blocked"
    assert "per-run" in state.note


def test_per_day_cost_cap_blocks(tmp_path: Path, runner: Runner, cfg) -> None:
    """Вчерашние траты не считаются; сегодняшние сверх капа блокируют задачу."""
    today = datetime.now(UTC).date().isoformat()
    old_run = cfg.runs_dir / "run-20000101-000000"
    old_run.mkdir(parents=True)
    event = {"ts": f"{today}T00:00:01+00:00", "run_id": old_run.name, "task_id": None,
             "phase": "run", "role": None, "model": None, "tokens_in": 0, "tokens_out": 0,
             "cost_usd": 999.0, "note": "seeded"}
    (old_run / "events.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")

    run_id = runner.run(write_tasks(tmp_path, TASK_OK))
    state = Journal(cfg.runs_dir, run_id).task_state("task-ok")
    assert state.state == "blocked"
    assert "per-day" in state.note
