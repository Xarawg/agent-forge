"""End-to-end прогон в mock-режиме (SPEC.md §6.2/§6.3): done, журнал, status/report."""

from pathlib import Path

from conftest import FORGE_ROOT, TASK_OK, write_tasks

from forge.journal import Journal
from forge.report import build_report, render_report, render_status
from forge.runner import Runner


def test_mock_run_done(runner: Runner, cfg, target: Path, tmp_path: Path) -> None:
    run_id = runner.run(write_tasks(tmp_path, TASK_OK), spec_path=FORGE_ROOT / "SPEC.md")

    journal = Journal(cfg.runs_dir, run_id)
    state = journal.task_state("task-ok")
    assert state.state == "done"
    assert state.tokens_in > 0  # usage журналируется (SPEC.md §FR-4)
    # mock-coder реально записал файл в scope целевого репо
    assert (target / "out" / "mock_output.md").exists()

    events = journal.read_events()
    phases = {e["phase"] for e in events}
    assert {"coder", "validate", "review", "state"} <= phases
    # ни одно событие не содержит api-ключей (NFR-3)
    assert all("api_key" not in str(e).lower() for e in events)

    report = build_report(cfg.runs_dir, run_id)
    assert report.tasks[0].state == "done"
    text = render_report(report, cfg.budgets.per_run_max_cost_usd)
    assert "Итого стоимость" in text
    assert "Версия промптов" in text
    assert render_status(report).count("task-ok") == 1


def test_scope_violation_logged(runner: Runner, cfg, tmp_path: Path, monkeypatch) -> None:
    """§6.5: попытка coder'а писать вне scope блокируется и логируется."""
    monkeypatch.setenv("FORGE_MOCK_SCENARIO", "rogue")
    run_id = runner.run(write_tasks(tmp_path, TASK_OK))

    journal = Journal(cfg.runs_dir, run_id)
    violations = [e for e in journal.read_events() if "SCOPE_VIOLATION" in e.get("note", "")]
    assert violations, "нарушение scope должно быть в журнале"
    # инструмент отказал, файл не создан, задача всё равно доехала до done
    assert not (runner.target / "outside_scope").exists()
    assert journal.task_state("task-ok").state == "done"


def test_gate_blocks_until_accept(runner: Runner, cfg, tmp_path: Path) -> None:
    """Человеческий гейт №3 (§FR-4): после задачи с gate прогон стопорится до accept."""
    tasks = write_tasks(tmp_path, """\
package: gated
tasks:
  - id: gated-task
    title: "Задача с гейтом"
    spec_ref: "SPEC.md"
    scope_paths: ["out/**"]
    acceptance:
      - "python -c \\"print('ok')\\""
    gate: pilot-1
  - id: next-task
    title: "Следующая"
    spec_ref: "SPEC.md"
    scope_paths: ["out/**"]
    depends_on: [gated-task]
    acceptance:
      - "python -c \\"print('ok')\\""
""")
    run_id = runner.run(tasks)
    journal = Journal(cfg.runs_dir, run_id)
    assert journal.task_state("gated-task").state == "done"
    assert journal.task_state("next-task").state == "queued"  # гейт удержал

    runner.accept(run_id, "gated-task")
    runner.run(tasks, run_id=run_id)  # resume
    assert journal.task_state("next-task").state == "done"
    assert "gated-task" in journal.accepted_tasks()


def test_accept_overrides_blocked(runner: Runner, cfg, tmp_path: Path) -> None:
    """Override гейта №3: blocked/failed-задачу владелец может принять вручную,
    иначе кап бюджета делает её вечным тупиком при resume."""
    tasks = write_tasks(tmp_path, TASK_OK)
    run_id = runner.run(tasks)
    journal = Journal(cfg.runs_dir, run_id)

    state = journal.task_state("task-ok")
    state.state = "blocked"
    journal.set_task_state(state, note="per-task кап токенов исчерпан")

    runner.accept(run_id, "task-ok")
    assert journal.task_state("task-ok").state == "done"
    assert "override" in journal.task_state("task-ok").note
    assert "task-ok" in journal.accepted_tasks()
