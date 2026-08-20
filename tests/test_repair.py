"""Repair-цикл (SPEC.md §FR-3, §6.4): починка ≤3 итераций или failed с журналом."""

from pathlib import Path

from conftest import write_tasks

from forge.journal import Journal
from forge.runner import Runner


def _tasks_yaml(expected_iteration: int) -> str:
    check = (
        "import pathlib,sys; "
        "p=pathlib.Path('out/mock_state.txt'); "
        f"sys.exit(0 if p.exists() and p.read_text().strip()=='iteration-{expected_iteration}' else 1)"
    )
    return f"""\
package: repair-test
tasks:
  - id: repair-task
    title: "Задача с ломающейся приёмкой"
    spec_ref: "SPEC.md"
    scope_paths: ["out/**"]
    acceptance:
      - "python -c \\"{check}\\""
"""


def test_repair_heals_within_limit(runner: Runner, cfg, tmp_path: Path) -> None:
    """Mock-repair пишет mock_state.txt на итерации 1 → acceptance зеленеет."""
    run_id = runner.run(write_tasks(tmp_path, _tasks_yaml(expected_iteration=1)))
    journal = Journal(cfg.runs_dir, run_id)
    state = journal.task_state("repair-task")
    assert state.state == "done"
    assert state.repair_iterations == 1
    phases = [e["phase"] for e in journal.log_for_task("repair-task")]
    assert "repair" in phases and "validate" in phases and "review" in phases


def test_repair_exhausted_fails_with_journal(runner: Runner, cfg, tmp_path: Path) -> None:
    """Непочиняемая приёмка: 3 итерации → failed, журнал объясняет почему."""
    run_id = runner.run(write_tasks(tmp_path, _tasks_yaml(expected_iteration=99)))
    journal = Journal(cfg.runs_dir, run_id)
    state = journal.task_state("repair-task")
    assert state.state == "failed"
    assert state.repair_iterations == 3
    assert "repair-итерац" in state.note

    events = journal.log_for_task("repair-task")
    repair_calls = [e for e in events if e["phase"] == "repair" and e.get("role") == "repair"]
    assert repair_calls, "repair-вызовы должны быть в журнале"
    red_validations = [e for e in events if e["phase"] == "validate" and e.get("exit_code") != 0]
    assert len(red_validations) >= 3  # каждая итерация честно красная
