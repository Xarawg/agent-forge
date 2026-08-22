"""Dogfooding-находки живого прогона 2026-08-22:

1. report считал «N из M» только по тронутым задачам (M — по пакету tasks.yaml).
2. status не показывал, что прогон стоит на человеческом гейте (ждёт forge accept).
3. runner стартовал задачу, чья зависимость blocked/failed (DAG не стопорился).
"""

from pathlib import Path

from forge.journal import Journal
from forge.models import Task, TaskState
from forge.report import build_report, render_plain, render_status
from forge.runner import Runner
from tests.conftest import write_tasks

TASKS_YAML = """\
package: dogfood
tasks:
- id: a-first
  title: Первая
  spec_ref: тест
  scope_paths: [a.py]
  acceptance: ["true"]
  gate: review
- id: b-second
  title: Вторая
  spec_ref: тест
  scope_paths: [b.py]
  depends_on: [a-first]
  acceptance: ["true"]
  gate: review
- id: c-third
  title: Третья
  spec_ref: тест
  scope_paths: [c.py]
  depends_on: [b-second]
  acceptance: ["true"]
"""


def _run(runs_dir: Path, tasks_path: Path, states: list[tuple[str, str]],
         accepted: list[str] | None = None) -> str:
    journal = Journal(runs_dir, "run-20990101-000000")
    journal.write_meta({
        "run_id": journal.run_id, "provider": "mock", "mock": True,
        "models": {}, "accepted": accepted or [], "tasks_path": str(tasks_path),
    })
    for task_id, state in states:
        journal.set_task_state(TaskState(id=task_id, state=state))
    return journal.run_id


def test_report_counts_queued_from_tasks_path(cfg, tmp_path: Path) -> None:
    """Тронута одна задача из трёх — отчёт обязан сказать «1 из 3», а не «1 из 1»."""
    tasks = write_tasks(tmp_path, TASKS_YAML)
    run_id = _run(cfg.runs_dir, tasks, [("a-first", "done")])
    report = build_report(cfg.runs_dir, run_id)
    assert [t.task_id for t in report.tasks] == ["a-first", "b-second", "c-third"]
    assert [t.state for t in report.tasks] == ["done", "queued", "queued"]
    assert "Сделано: 1 из 3" in render_plain(report)


def test_report_without_tasks_path_keeps_old_behavior(cfg) -> None:
    """tasks_path нет/битый — отчёт по журналу, как раньше (без падения)."""
    journal = Journal(cfg.runs_dir, "run-20990101-000000")
    journal.write_meta({"run_id": journal.run_id, "accepted": [],
                        "tasks_path": str(cfg.runs_dir / "no-such.yaml")})
    journal.set_task_state(TaskState(id="a-first", state="done"))
    report = build_report(cfg.runs_dir, journal.run_id)
    assert [t.task_id for t in report.tasks] == ["a-first"]


def test_status_shows_gate_wait_hint(cfg, tmp_path: Path) -> None:
    """Done-задача с gate не принята, очередь стоит — status говорит, что делать."""
    tasks = write_tasks(tmp_path, TASKS_YAML)
    run_id = _run(cfg.runs_dir, tasks, [("a-first", "done")], accepted=[])
    text = render_status(build_report(cfg.runs_dir, run_id))
    assert f"⏸ Прогон ждёт решения: forge accept a-first && forge resume {run_id}" in text


def test_status_no_hint_after_accept(cfg, tmp_path: Path) -> None:
    tasks = write_tasks(tmp_path, TASKS_YAML)
    run_id = _run(cfg.runs_dir, tasks, [("a-first", "done")], accepted=["a-first"])
    text = render_status(build_report(cfg.runs_dir, run_id))
    assert "Прогон ждёт решения" not in text


def test_runner_blocks_dependent_of_failed_dependency(cfg) -> None:
    """Зависимость не done — зависимая задача не стартует (остановка на гейте)."""
    journal = Journal(cfg.runs_dir, "run-20990101-000000")
    journal.write_meta({"run_id": journal.run_id, "accepted": []})
    dep = Task(id="a-first", title="", spec_ref="", scope_paths=["a.py"])
    task = Task(id="b-second", title="", spec_ref="", scope_paths=["b.py"],
                depends_on=["a-first"])

    journal.set_task_state(TaskState(id="a-first", state="blocked"))
    assert Runner._unmet_dependency(journal, task) == "a-first"
    journal.set_task_state(TaskState(id="a-first", state="failed"))
    assert Runner._unmet_dependency(journal, task) == "a-first"
    journal.set_task_state(TaskState(id="a-first", state="done"))
    assert Runner._unmet_dependency(journal, task) is None
    assert Runner._unmet_dependency(journal, dep) is None  # без зависимостей — всегда ок
